Environment contract environment-v1:
Web reset restores the application within a task-declared bound, then waits up
to 10 seconds for DOMContentLoaded, an attached body and the task's declared
initial-screen landmarks. These identify the starting screen only,
equally in both variants; they never assert the desired task outcome.
A task that declares bundled local fonts also finishes its initial font load
inside that same ten-second deadline, after its starting landmarks are visible. This avoids
fallback-font screenshots in fresh contexts. The resource check applies only to
initial preparation; font loading never gates subsequent actions or observations.
It uses no goal assertion, animation condition or extended execution budget.
Targeted web actions use Playwright's built-in actionability waits (30-second
operation timeout). Navigation waits for DOMContentLoaded. After actions a shared
250 ms rendering pause allows immediate UI updates; it is not proof that background
work finished. Existing UI assertions retry for 1.5 seconds. Screenshots and UI
observations are not gated on global readiness, pixel stability, animations,
network quiet or busy flags. Repeated observations can inspect loading progress.
There are no app-specific animation selectors, masks or post-action wait rules.
Actions and trials are not replayed automatically.

Reset replaces the web browser context and task server state. A fresh neutral
session identifier fences stale server requests; reset acknowledgement is required.
Failed preparation/reset is an operation failure, never a successful fault detection.
Locale is en-US; viewport/timezone are pinned. Wall-clock time remains real time
unless a date-sensitive task declares its public browser Date epoch.
