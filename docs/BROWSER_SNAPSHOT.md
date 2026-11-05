# Browser snapshots and element refs

For reliable web automation JARVIS now reads a page as a short list instead of guessing CSS selectors:

1. `browser_control(action="snapshot")` → lines such as `[e3] button "Search"`, `[e2] textbox "Search products" value=""`,
   `[e1] link "Cart (2)" -> /cart`. Only visible interactive elements are listed (max 150); password values are never read.
2. `click_ref` / `type_ref` (optional `submit`) / `select_ref` (dropdowns and checkboxes) act on a ref.
3. Every action reports what changed — URL, title, whether the element is still there, and for typing whether the field
   really holds the text — so a failed step is noticed instead of assumed.

A ref belongs to one snapshot of one page: after navigation or when the element disappears the action refuses and asks for a new
snapshot. Snapshot text is page content, so it is wrapped as untrusted external content. `snapshot` is SAFE tier; the `*_ref`
actions are DANGEROUS tier like `click`/`type`. Not covered yet: iframes, shadow DOM, drag and drop, and the user's native
(non-controlled) browser window. The older `click`, `type`, `smart_click` actions are unchanged.
