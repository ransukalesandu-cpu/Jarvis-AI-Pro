# JARVIS Local Day Planner and Event Memory

## What it does

The daily_planner action gives JARVIS a persistent local list of plans, events, and unfinished tasks. When a plan item has both a date and a time, JARVIS asks the existing operating-system reminder scheduler to create a native notification/alarm. Different reminders scheduled for the same minute use different task names, so they do not overwrite each other.

## Voice examples

- "Plan my day: physics at 8 AM, ICT at 10:30, and gym at 5 PM."
- "Remember that I need to submit the application tomorrow."
- "Remind me to call the tutor at 9 AM tomorrow."
- "What's my plan for today?"
- "What did I forget to do?" / "Give me a check-in."
- "I finished physics revision." / "Mark call the tutor as complete."
- "Move the tutor call to Friday at 10 AM."
- "Forget the application task."

JARVIS resolves natural-language dates and times into the tool's required local values (YYYY-MM-DD and HH:MM). If it cannot resolve a date/time safely, it should ask a follow-up rather than invent one.

## How it works

- A plan can contain multiple activities; each item with a date and time gets its own OS reminder.
- Items without a time are still saved, but JARVIS does not claim an alarm was set.
- Saved items remain in ~/.jarvis/daily_planner.json across JARVIS restarts. The path may be overridden with JARVIS_PLANNER_FILE for testing or managed deployments.
- The planner supports listing today's items or upcoming items, a check-in covering overdue pending tasks plus today's plan and undated remembered tasks, marking tasks complete, rescheduling, and forgetting an item.
- When a future alarm is cancelled or an item is removed, JARVIS asks the operating system to cancel the matching scheduled job. If the scheduler cannot confirm cancellation, a delete is refused and the saved item is retained. Marking an item complete can still succeed, but JARVIS warns if an OS alarm may remain.
- Planner files are written atomically and restricted to the current OS account where the platform supports file permissions. Only the short details needed to recall the item are stored; raw conversation history is not stored.

## Limits and privacy

This planner is local to the current OS account and is not synced to Supabase or other devices. Notifications depend on the operating system scheduler, logged-in user/session, notification permissions, and device power state. A computer that is shut down or has notifications disabled may not show an alert at the requested time. It is not a replacement for a safety-critical alarm.

The saved file is a local convenience, not an authoritative calendar. Review it regularly and explicitly mark finished work complete so later check-ins do not mistake it for unfinished work. Google Calendar remains separate and still requires connecting the Google account.
