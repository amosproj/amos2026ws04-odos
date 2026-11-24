# Validation preview source controls and generated-rule download

The next-page title is Validate your digital twin. The Next step eyebrow is removed. Rule source shows the generated Rule JSON filename when available, with Upload Rule JSON to select a local replacement and Use extracted rules to restore the generated source. The digital twin picker is a click/keyboard/drop field; native file-picker rows are hidden. Both source and twin pickers accept JSON only. JSON-LD is no longer listed or accepted by filename. The bottom note is exactly: Validation is not connected yet.

The rule extraction/review results page now shows Download Rule JSON once an existing/generated rules artifact is available. It downloads the backend rules.json artifact directly and does not trigger extraction. The existing approved-rule export remains separate. The validation page is still a UI preview: uploaded selections stay local, no contents are read or sent, and Validate produces no compliance verdict. Changing either selected file clears the preview message.

This cumulative update includes the article checklist, stop/preservation and current 1/3-call dropdown. Merge the ZIP folders into the current project root, replace matching files, keep .env and all other project files, and run:

```powershell
docker compose up --build -d
```

Checks: changed TS/TSX parsed/transpiled. Lightweight component checks covered the exact heading/note, hidden JSON-only pickers, source selection/reset, click/keyboard/drop actions, rejecting unsupported extensions, mock-only output, no network calls, back navigation, and the generated-rule download URL/name and availability gate. Full TypeScript/Vitest/Docker build was not run here.
