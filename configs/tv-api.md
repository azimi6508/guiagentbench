TV tools: gui_observe returns the application screenshot at the declared viewport.
gui_step accepts exactly {"action":"press","key":"up"}. Remote keys are back,
down, exit, left, menu, ok, right and up. gui_reset restores the initial screen
(or the prepared final checkpoint when authoring an oracle). There is no URL,
pointer, application source, hidden state selection or UI tree. The task goal and
visible application behavior define what each permitted remote action does.
