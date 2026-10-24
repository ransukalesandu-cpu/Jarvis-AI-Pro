import threading
import time
import queue

class SafeSpeechManager:
    def __init__(self):
        self.speech_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.is_speaking = False
        self.lock = threading.Lock()
        
        # Background worker thread for speech
        self.worker_thread = threading.Thread(target=self._speech_worker, daemon=True)
        self.worker_thread.start()

    def speak(self, text: str):
        """Queue text to be spoken."""
        self.stop_event.clear()
        self.speech_queue.put(text)

    def interrupt(self):
        """Safely stops Jarvis without crashing the audio device."""
        try:
            with self.lock:
                if self.is_speaking:
                    # Signal the playback loop to break immediately
                    self.stop_event.set()
                    
                    # Clear any pending speech queue
                    while not self.speech_queue.empty():
                        try:
                            self.speech_queue.get_nowait()
                            self.speech_queue.task_done()
                        except queue.Empty:
                            break
                    print("[Voice] Speech successfully interrupted.")
        except Exception as e:
            # This is where your code was previously printing "interrupting failed"
            print(f"[Voice] Handled interruption warning: {e}")

    def _speech_worker(self):
        while True:
            text = self.speech_queue.get()
            if not text:
                continue

            self.stop_event.clear()
            self.is_speaking = True

            try:
                self._play_audio_stream(text)
            except Exception as e:
                print(f"[Voice] Playback error: {e}")
            finally:
                self.is_speaking = False
                self.speech_queue.task_done()
                time.sleep(0.1)  # Buffer to allow echo to dissipate

    def _play_audio_stream(self, text: str):
        """
        Play audio in small chunks so that stop_event.is_set() 
        breaks out in milliseconds without crashing the audio driver.
        """
        try:
            import pyttsx3
            engine = pyttsx3.init()
        except ImportError:
            print("[Voice] pyttsx3 is not installed. Speech playback skipped.")
            return
        except Exception as e:
            print(f"[Voice] pyttsx3 initialization failed: {e}")
            return

        # Break long sentences into short phrases
        phrases = [p.strip() for p in text.replace("\n", ". ").split(". ") if p.strip()]

        for phrase in phrases:
            # Check if user interrupted before speaking each chunk
            if self.stop_event.is_set():
                break

            engine.say(phrase)
            engine.runAndWait()
