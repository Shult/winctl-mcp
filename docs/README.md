# Documentation assets

## `demo.gif` — to be added

The README reserves a spot for a demo, right under the tagline. It is the first
thing a visitor sees, and on a project like this one it is what decides: "drives
a PC" is an unverifiable promise until you have seen it.

Drop the file here under the name `demo.gif`, then replace the
`DEMO PLACEHOLDER` comment block in `../README.md` with:

```markdown
![Demo](docs/demo.gif)
```

What works well, in decreasing order of strength:

1. **A short, complete round trip** — an instruction in natural language, the
   screenshot, a few clicks, the visible result. Twenty seconds is enough.
2. **The screen and the conversation side by side**, so the decision and its
   effect appear in the same frame.
3. **An ordinary, recognisable task** rather than a technical demonstration:
   renaming files, filling a form, extracting a value from an application with
   no API.

Two precautions before publishing: the GIF shows your real desktop — check the
taskbar, the notifications, the window titles and the browser tabs. And keep the
file under 10 MB, beyond which GitHub stops animating it in the README.
