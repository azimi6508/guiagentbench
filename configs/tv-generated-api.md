Author a Python program using the available TV screens and remote tools.
The same sealed program and your chosen named screenshot references run on two
fresh environments. You choose the references, crops, masks and tolerances.
There is no authoring-time execution or grading feedback.

Execution exposes page.screenshot() and page.expect_image(...), described below.
Full tests also have page.press(key) for the remote keys and page.reset().
Oracle execution cannot act or reset. Both need a positive image precondition
and a behavior assertion. Check shared app chrome independently of the requested
destination/content. A destination or selected tab is part of behavior, even
when the expected destination is visible in your authoring session. An authored
precondition failure invalidates the oracle/test; it does not establish an
environment failure and does not count as fault detection. Comparison results stay in the trusted ledger; assertions
return None. No UI selectors, UI dumps, URL navigation, private reference check,
source data, graph inspection or baseline updates are available.
