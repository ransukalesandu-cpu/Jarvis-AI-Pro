"""Output-device stream setup and fallback helpers for JARVIS playback."""

from __future__ import annotations


import asyncio
import time
import traceback
from dataclasses import dataclass
from typing import Any

import numpy as np

from core.live_audio import (
    CHANNELS,
    RECEIVE_SAMPLE_RATE,
    _MIN_PREBUFFER_BYTES,
    _OUTPUT_BLOCKSIZE,
    _output_write_is_unpaced,
    _pcm_level,
)


@dataclass(frozen=True)
class OutputStreamOpenResult:
    """Stream selected by the user, or the OS default after a failed open."""

    stream: Any
    used_default: bool = False
    selected_device_error: Exception | None = None


def open_output_stream(
    audio_backend: Any,
    device: Any,
    sample_rate: int,
    channels: int,
    blocksize: int,
) -> Any:
    """Open and start a raw signed-16-bit PCM output stream."""
    if audio_backend is None:
        raise RuntimeError("sounddevice is unavailable (PortAudio missing)")
    stream = audio_backend.RawOutputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype="int16",
        blocksize=blocksize,
        device=device,
    )
    stream.start()
    return stream


def open_output_stream_with_fallback(
    *,
    audio_backend: Any,
    selected_device: Any,
    sample_rate: int,
    channels: int,
    blocksize: int,
) -> OutputStreamOpenResult:
    """Try the selected output, then the system default exactly once."""
    try:
        return OutputStreamOpenResult(
            stream=open_output_stream(
                audio_backend, selected_device, sample_rate, channels, blocksize
            )
        )
    except Exception as selected_error:
        if selected_device is None:
            raise
        stream = open_output_stream(audio_backend, None, sample_rate, channels, blocksize)
        return OutputStreamOpenResult(
            stream=stream,
            used_default=True,
            selected_device_error=selected_error,
        )


def describe_output_route(audio_backend: Any, device: Any) -> str:
    """Return a best-effort device/host-API label for diagnostics."""
    try:
        if audio_backend is None:
            return repr(device)
        info = audio_backend.query_devices(device, "output")
        hostapis = audio_backend.query_hostapis()
        host_index = int(info.get("hostapi", -1))
        api_name = (
            hostapis[host_index].get("name", "unknown host API")
            if 0 <= host_index < len(hostapis)
            else "unknown host API"
        )
        return f"{info.get('name', 'unknown device')} via {api_name}"
    except Exception:
        return repr(device)


def stream_device_index(active_stream: Any, requested_device: Any) -> Any:
    """Read a resolved output index from a stream, if the backend exposes it."""
    try:
        value = getattr(active_stream, "device", None)
        if isinstance(value, (tuple, list)):
            value = value[-1] if value else None
        if value is not None:
            return int(value)
    except (TypeError, ValueError, RuntimeError):
        pass
    return requested_device


async def open_verified_output_fallback(
    *,
    audio_backend: Any,
    device_service: Any,
    sample_rate: int,
    channels: int,
    blocksize: int,
    excluded_device: Any,
):
    """Find and open another output device after proving it accepts live output."""
    try:
        candidates = await asyncio.to_thread(device_service.list_devices, "output")
    except Exception as exc:
        print(f"[AudioTrace 4/OUTPUT] Could not enumerate fallback speakers: {exc}")
        return None

    for candidate_name in candidates:
        try:
            candidate_device = await asyncio.to_thread(
                device_service.resolve, candidate_name, "output"
            )
            if candidate_device is None or candidate_device == excluded_device:
                continue
            works = await asyncio.to_thread(
                device_service.probe_transport, candidate_device, "output"
            )
            if not works:
                continue
            candidate_stream = await asyncio.to_thread(
                open_output_stream,
                audio_backend,
                candidate_device,
                sample_rate,
                channels,
                blocksize,
            )
            return candidate_name, candidate_device, candidate_stream
        except Exception as exc:
            print(
                f"[AudioTrace 4/OUTPUT] Fallback speaker "
                f"{candidate_name!r} unavailable: {exc}"
            )
    return None



async def run_audio_playback(
    host,
    *,
    audio_backend,
    device_service,
    get_output_device_fn,
    pcm_visemes_fn,
    output_executor,
    tail_margin: float,
    first_sound_delay: float,
    cursor_slack: float,
    viseme_hop: int,
) -> None:
    print("[JARVIS] 🔊 Play started")
    print("[AudioTrace 4/OUTPUT] Playback worker running; waiting for Live PCM chunks.")

    first_output_chunk_logged = False
    first_output_write_started = False
    first_output_write_completed = False
    first_phone_audio_logged = False
    output_audio_seconds = 0.0
    output_write_wall_seconds = 0.0
    output_write_count = 0
    output_timing_diagnostic_done = False
    last_output_write_end = None
    last_queue_starvation_log = 0.0
    write_recovery_attempted = False

    _spk_name = get_output_device_fn()
    _spk_dev  = device_service.resolve(_spk_name, "output")
    if _spk_dev is not None:
        print(f"[JARVIS] 🔊 Output device: {_spk_name}")

    output_open = open_output_stream_with_fallback(
        audio_backend=audio_backend,
        selected_device=_spk_dev,
        sample_rate=RECEIVE_SAMPLE_RATE,
        channels=CHANNELS,
        blocksize=_OUTPUT_BLOCKSIZE,
    )
    stream = output_open.stream
    if output_open.used_default:
        _e = output_open.selected_device_error
        print(f"[JARVIS] ⚠️  Output device '{_spk_name}' failed: {_e} — using default")
        host.ui.write_log(f"SYS: Speaker '{_spk_name}' unavailable — using system default.")
        _spk_name = ""
        _spk_dev = None

    host._output_stream = stream
    print(
        f"[AudioTrace 4/OUTPUT] Output stream ready: requested_device={_spk_name or 'system default'!r}, "
        f"resolved_device={_spk_dev!r}, sample_rate={RECEIVE_SAMPLE_RATE} Hz."
    )
    print(
        f"[AudioTrace 4/OUTPUT] Active route: {describe_output_route(audio_backend, _spk_dev)}; "
        f"stream_active={bool(getattr(stream, 'active', False))}."
    )

    # Ask the device how far behind the speakers actually are, rather than
    # assuming. This is what the echo tail is sized from, so a machine with a
    # large audio buffer gets a correspondingly longer guard — and one with a
    # tiny buffer is not penalised with a delay it does not need.
    try:
        lat = float(getattr(stream, "latency", 0.0) or 0.0)
        if 0.0 < lat < 1.0:
            host._out_latency = lat
        print(f"[JARVIS] 🔊 Output latency {host._out_latency*1000:.0f} ms "
              f"→ echo tail {(host._out_latency + tail_margin)*1000:.0f} ms")
    except Exception:
        pass

    pending_pcm = bytearray()
    playback_started = False
    prebuffer_logged = False
    try:
        while True:
            # An interruption must discard both queued and locally buffered
            # PCM, otherwise the old response could resume after barge-in.
            if host._playback_interrupt_requested.is_set():
                pending_pcm.clear()
                playback_started = False
                host._playback_interrupt_requested.clear()
                try:
                    if not stream.active:
                        stream.start()
                except Exception as exc:
                    print(f"[JARVIS] Could not resume output after interrupt: {exc}")
                continue

            if host._shutdown_requested:
                break

            interrupted_while_buffering = False

            # Maintain a ~300 ms jitter buffer before the first write and
            # whenever the local buffer falls below target. This gives Live
            # audio a chance to arrive before the speaker queue runs dry.
            while len(pending_pcm) < _MIN_PREBUFFER_BYTES and not playback_started:
                if host._shutdown_requested:
                    break
                if host._playback_interrupt_requested.is_set():
                    pending_pcm.clear()
                    playback_started = False
                    host._playback_interrupt_requested.clear()
                    try:
                        if not stream.active:
                            stream.start()
                    except Exception as exc:
                        print(f"[JARVIS] Could not resume output after interrupt: {exc}")
                    interrupted_while_buffering = True
                    break

                try:
                    next_chunk = await asyncio.wait_for(
                        host.audio_in_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if host._shutdown_requested:
                        break
                    now_mono = time.monotonic()
                    turn_complete = bool(
                        host._turn_done_event
                        and host._turn_done_event.is_set()
                    )
                    queue_empty = host.audio_in_queue.empty()

                    if (
                        playback_started
                        and host._assistant_turn_pending
                        and not turn_complete
                        and last_output_write_end is not None
                        and now_mono - last_output_write_end >= 0.10
                        and now_mono - last_queue_starvation_log >= 1.0
                    ):
                        print(
                            "[AudioTrace 4/BUFFER] PCM prebuffer fell below "
                            f"300 ms while the assistant turn was pending; "
                            f"buffered={len(pending_pcm)} bytes, waiting for Live audio."
                        )
                        last_queue_starvation_log = now_mono

                    # Short replies must not be held forever waiting for
                    # 300 ms that will never arrive. Flush remaining audio
                    # once Live confirms the turn is complete.
                    if turn_complete and queue_empty:
                        if pending_pcm:
                            if not playback_started:
                                print(
                                    "[AudioTrace 4/BUFFER] Short response: flushing "
                                    f"{len(pending_pcm)} buffered PCM bytes below the "
                                    "300 ms prebuffer target."
                                )
                                playback_started = True
                            break

                        host.set_speaking(False)
                        host._turn_done_event.clear()
                        playback_started = False
                        prebuffer_logged = False
                        continue
                    continue

                if host._playback_interrupt_requested.is_set():
                    pending_pcm.clear()
                    playback_started = False
                    host._playback_interrupt_requested.clear()
                    try:
                        if not stream.active:
                            stream.start()
                    except Exception as exc:
                        print(f"[JARVIS] Could not resume output after interrupt: {exc}")
                    interrupted_while_buffering = True
                    break

                pending_pcm.extend(next_chunk)

            if interrupted_while_buffering:
                continue

            if not playback_started:
                if len(pending_pcm) >= _MIN_PREBUFFER_BYTES:
                    playback_started = True
                    if not prebuffer_logged:
                        print(
                            "[AudioTrace 4/BUFFER] PCM prebuffer ready: "
                            f"{len(pending_pcm)} bytes "
                            f"(target={_MIN_PREBUFFER_BYTES} bytes, about 300 ms)."
                        )
                        prebuffer_logged = True
                else:
                    continue

            if not pending_pcm:
                # Only prebuffer the beginning of a response. Once playback
                # has started, wait for the next PCM chunk instead of spinning
                # or rebuilding the 300 ms prebuffer after every batch.
                try:
                    next_chunk = await asyncio.wait_for(
                        host.audio_in_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    turn_complete = bool(
                        host._turn_done_event
                        and host._turn_done_event.is_set()
                    )
                    if turn_complete and host.audio_in_queue.empty():
                        host.set_speaking(False)
                        host._turn_done_event.clear()
                        playback_started = False
                        prebuffer_logged = False
                    elif (
                        host._assistant_turn_pending
                        and not turn_complete
                        and host.audio_in_queue.empty()
                    ):
                        # Live audio can arrive in bursts. If the speaker queue
                        # has actually run dry mid-turn, re-arm the jitter buffer
                        # so the next burst is not played after a single 50 ms
                        # slice. This cannot hide long server/network stalls, but
                        # it smooths short underruns instead of repeatedly
                        # starting playback with no reserve.
                        playback_started = False
                        prebuffer_logged = False
                        now_mono = time.monotonic()
                        if now_mono - last_queue_starvation_log >= 1.0:
                            print(
                                "[AudioTrace 4/BUFFER] Output underrun; "
                                "rebuffering before playback resumes."
                            )
                            last_queue_starvation_log = now_mono
                    continue

                if host._playback_interrupt_requested.is_set():
                    host._playback_interrupt_requested.clear()
                    host.set_speaking(False)
                    pending_pcm.clear()
                    playback_started = False
                    try:
                        if not stream.active:
                            stream.start()
                    except Exception as exc:
                        print(f"[JARVIS] Could not resume output after interrupt: {exc}")
                    continue
                pending_pcm.extend(next_chunk)
                if not pending_pcm:
                    continue

            batch = bytearray(pending_pcm[:4800])
            del pending_pcm[:len(batch)]

            if not first_output_chunk_logged:
                print(
                    "[AudioTrace 4/OUTPUT] First buffered PCM batch ready for playback "
                    f"({len(batch)} bytes; prebuffer target={_MIN_PREBUFFER_BYTES} bytes)."
                )
                first_output_chunk_logged = True

            host.set_speaking(True)

            # Drive the HUD waveform and the avatar's mouth from JARVIS's
            # own voice. The batch is up to 100 ms long, so we hand over a
            # *schedule* of 20 ms viseme frames instead of a single averaged
            # level and let the HUD play it out in step with the audio.
            try:
                pcm = np.frombuffer(bytes(batch), dtype=np.int16)
                hop = viseme_hop / RECEIVE_SAMPLE_RATE
                frames = pcm_visemes_fn(pcm, sr=RECEIVE_SAMPLE_RATE)
                # When does this batch become audible? The stream was
                # started at launch and its callback has been pulling
                # silence ever since, so the first bytes of a reply reach
                # the speaker about one callback period later — NOT one
                # buffer later. `stream.latency` reports the buffer's
                # capacity, which is how much can be queued ahead, and on
                # Windows that is commonly 300-500 ms. Anchoring on it put
                # the entire schedule a buffer late; that is the half second
                # of lag, and it grew with whatever the device reported.
                #
                # After the anchor nothing needs measuring: the device
                # consumes at exactly realtime, so each batch sounds one
                # batch-duration after the one before it. The cursor is
                # re-anchored only when it leaves the range physically
                # possible — behind `now` means the device drained and this
                # batch starts a fresh stretch of speech, while further
                # ahead than the buffer can hold means it has drifted.
                now = time.time()
                horizon = host._out_latency + cursor_slack
                if not (now <= host._play_cursor <= now + horizon):
                    host._play_cursor = now + first_sound_delay
                at = host._play_cursor
                # Advance by the batch's own duration whether or not it
                # yielded frames, so a block too short to analyse cannot
                # shift everything after it out of step with the audio.
                host._play_cursor += pcm.size / RECEIVE_SAMPLE_RATE
                if frames:
                    frames = host._visemes.frames(frames, hop)
                    host.ui.push_visemes(frames, hop, at)
                    # Barge-in needs to know what we are playing, not just
                    # how loud: the guard subtracts this from the microphone.
                    host._out_level = max(f[0] for f in frames)
                    host._echo.note_output(pcm, RECEIVE_SAMPLE_RATE,
                                           host._out_level)
                else:
                    lvl = _pcm_level(pcm)
                    host.ui.set_audio_level(lvl)
                    host._out_level = lvl
                    host._echo.note_output(pcm, RECEIVE_SAMPLE_RATE, lvl)
            except Exception:
                pass

            # While the paired phone is streaming its microphone, route
            # JARVIS's reply audio to that same phone session. Never fall
            # back to PC speakers during an active phone handoff: a lost
            # phone connection should fail quiet until its mic stops.
            if host._phone_active:
                if not first_phone_audio_logged:
                    print("[AudioTrace 4/OUTPUT] Phone handoff is active; routing reply audio to the phone, not PC speakers.")
                    first_phone_audio_logged = True
                delivered = False
                if host._dashboard is not None and not host.ui.muted:
                    try:
                        delivered = await host._dashboard.send_phone_audio(bytes(batch))
                    except Exception:
                        delivered = False
                if not delivered:
                    continue
            else:
                try:
                    if not first_output_write_started:
                        print(
                            f"[AudioTrace 4/OUTPUT] Calling sounddevice.write for first batch "
                            f"({len(batch)} bytes)."
                        )
                        first_output_write_started = True
                    write_started = time.perf_counter()
                    await asyncio.get_running_loop().run_in_executor(
                        output_executor, stream.write, bytes(batch)
                    )
                    write_elapsed = max(0.0, time.perf_counter() - write_started)
                    batch_audio_seconds = len(batch) / (
                        RECEIVE_SAMPLE_RATE * CHANNELS * 2
                    )
                    output_audio_seconds += batch_audio_seconds
                    output_write_wall_seconds += write_elapsed
                    output_write_count += 1
                    last_output_write_end = time.monotonic()

                    if output_write_count <= 4:
                        print(
                            f"[AudioTrace 4/OUTPUT] Write timing #{output_write_count}: "
                            f"{len(batch)} bytes (~{batch_audio_seconds * 1000:.0f} ms PCM) "
                            f"accepted in {write_elapsed * 1000:.0f} ms; "
                            f"queue_chunks={host.audio_in_queue.qsize()}."
                        )

                    if (
                        not output_timing_diagnostic_done
                        and output_audio_seconds >= 1.0
                    ):
                        output_timing_diagnostic_done = True
                        if _output_write_is_unpaced(
                            output_audio_seconds, output_write_wall_seconds
                        ):
                            print(
                                "[AudioTrace 4/OUTPUT] WARNING: submitted "
                                f"{output_audio_seconds * 1000:.0f} ms of PCM in only "
                                f"{output_write_wall_seconds * 1000:.0f} ms of write time. "
                                "The current endpoint may be accepting audio without "
                                "playing it in real time; attempting a tested speaker fallback."
                            )
                            current_device = stream_device_index(stream, _spk_dev)
                            fallback = await open_verified_output_fallback(
                        audio_backend=audio_backend,
                        device_service=device_service,
                        sample_rate=RECEIVE_SAMPLE_RATE,
                        channels=CHANNELS,
                        blocksize=_OUTPUT_BLOCKSIZE,
                        excluded_device=current_device,
                    )
                            if fallback is None:
                                print(
                                    "[AudioTrace 4/OUTPUT] No alternate tested speaker "
                                    "endpoint was available. Check Windows output device "
                                    "and volume settings."
                                )
                            else:
                                fallback_name, fallback_device, fallback_stream = fallback
                                old_stream = stream
                                stream = fallback_stream
                                host._output_stream = stream
                                _spk_name = fallback_name
                                _spk_dev = fallback_device
                                try:
                                    old_stream.stop()
                                except Exception:
                                    pass
                                try:
                                    old_stream.close()
                                except Exception:
                                    pass
                                output_audio_seconds = 0.0
                                output_write_wall_seconds = 0.0
                                output_write_count = 0
                                print(
                                    f"[AudioTrace 4/OUTPUT] Switched to tested speaker "
                                    f"{_spk_name!r} (device {_spk_dev}); "
                                    f"route={describe_output_route(audio_backend, _spk_dev)}. "
                                    "Replaying the last PCM batch."
                                )
                                replay_started = time.perf_counter()
                                await asyncio.get_running_loop().run_in_executor(
                        output_executor, stream.write, bytes(batch)
                    )
                                replay_elapsed = max(
                                    0.0, time.perf_counter() - replay_started
                                )
                                output_audio_seconds = batch_audio_seconds
                                output_write_wall_seconds = replay_elapsed
                                output_write_count = 1
                                last_output_write_end = time.monotonic()
                                print(
                                    f"[AudioTrace 4/OUTPUT] Fallback replay accepted "
                                    f"in {replay_elapsed * 1000:.0f} ms."
                                )
                        else:
                            print(
                                "[AudioTrace 4/OUTPUT] Output pacing check: "
                                f"{output_audio_seconds * 1000:.0f} ms of PCM took "
                                f"{output_write_wall_seconds * 1000:.0f} ms of write time; "
                                "no silent/unpaced endpoint signature detected."
                            )

                    if not first_output_write_completed:
                        print(
                            "[AudioTrace 4/OUTPUT] First sounddevice.write returned; "
                            "PortAudio accepted the PCM batch (this does not guarantee audible sound)."
                        )
                        first_output_write_completed = True
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if host._playback_interrupt_requested.is_set():
                        host._playback_interrupt_requested.clear()
                        host.set_speaking(False)
                        try:
                            if not stream.active:
                                stream.start()
                        except Exception as restart_exc:
                            print(f"[JARVIS] Could not resume output after interrupt: {restart_exc}")
                            raise
                        continue
                    if host._shutdown_requested:
                        break
                    print(f"[AudioTrace 4/OUTPUT] Speaker write failed: {type(exc).__name__}: {exc}")
                    traceback.print_exc()

                    # A device may open successfully but fail on its first real
                    # write (for example after Windows changes the default route).
                    # Try the system-default endpoint once, then fail clearly if
                    # that route also cannot accept audio.
                    if not write_recovery_attempted and _spk_dev is not None:
                        write_recovery_attempted = True
                        fallback_stream = None
                        try:
                            fallback_stream = await asyncio.to_thread(open_output_stream, audio_backend, None, RECEIVE_SAMPLE_RATE, CHANNELS, _OUTPUT_BLOCKSIZE)
                            old_stream = stream
                            stream = fallback_stream
                            host._output_stream = stream
                            _spk_name = ""
                            _spk_dev = None
                            try:
                                old_stream.stop()
                            except Exception:
                                pass
                            try:
                                old_stream.close()
                            except Exception:
                                pass
                            print(
                                "[AudioTrace 4/OUTPUT] Recovered from speaker write "
                                "failure by switching to the system-default output; "
                                "retrying the current PCM batch once."
                            )
                            retry_started = time.perf_counter()
                            await asyncio.get_running_loop().run_in_executor(
                                output_executor, stream.write, bytes(batch)
                            )
                            retry_elapsed = max(0.0, time.perf_counter() - retry_started)
                            retry_audio_seconds = len(batch) / (
                                RECEIVE_SAMPLE_RATE * CHANNELS * 2
                            )
                            output_audio_seconds += retry_audio_seconds
                            output_write_wall_seconds += retry_elapsed
                            output_write_count += 1
                            last_output_write_end = time.monotonic()
                            continue
                        except asyncio.CancelledError:
                            raise
                        except Exception as recovery_exc:
                            print(
                                "[AudioTrace 4/OUTPUT] System-default speaker recovery "
                                f"failed: {type(recovery_exc).__name__}: {recovery_exc}"
                            )
                            if fallback_stream is not None:
                                try:
                                    fallback_stream.stop()
                                except Exception:
                                    pass
                                try:
                                    fallback_stream.close()
                                except Exception:
                                    pass
                            host._output_stream = None
                    raise
    except Exception as e:
        print(f"[JARVIS] ❌ Play: {e}")
        raise
    finally:
        host.set_speaking(False)
        output_stream = host._output_stream
        host._output_stream = None
        try:
            from security.lockdown import teardown_audio_stream
            teardown_audio_stream(output_stream or stream)
        except Exception:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
