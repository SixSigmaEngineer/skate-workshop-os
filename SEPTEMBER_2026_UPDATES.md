# September 2026 updates

These changes address the six items in `Bugs 9_2026.docx`. They are in the application source. Restart SKATE using **Start SKATE.bat** in this folder to load them. An already running server must be stopped first. Existing installed executables need a new build to include these changes.

## 1. Sidebar and window layout

The sidebar fills the remaining window height and scrolls independently. Its height follows the header and the app's zoom setting. The header wraps its controls when space is limited.

## 2. Long transcripts and unrelated conversation

In a note, enter an optional **Workshop focus**, then choose **Clean/Compress Notes** or the transcript summary control. Cleanup checks the whole input, removes recognizable social chatter and repeated segments, and processes long text in sections. It no longer silently uses only the beginning of a long note.

Review the proposed notes and excluded text before selecting **Use reviewed notes**. You can edit the proposal or select **Keep original**. Applying a proposal saves the original text as a linked `.txt` attachment. Select **Save note** to finish. The original attachment remains outside the workshop note index so it does not feed the removed chatter back into analysis.

Spotter, Spotter Live, and GRIND also screen recognizable unrelated conversation. With AI disabled, cleanup preserves marked observations, pains, actions, questions, insights, solutions, recommendations, and decisions. Uncertain prose remains context instead of automatically becoming a pain or action. Local filtering uses conservative text rules; it cannot understand every tangent. Workshop focus and review remain useful, especially for specialist subjects and personal stories that describe real user needs.

## 3. Skateboard themes

Open **Settings → Appearance**. The dropdown shows skateboard photos and previews their matching colors. Choose a style and select **Save Settings** to keep it.

Select **Open board folder** to find the replaceable photos. Keep the existing filenames when swapping images. Edit `themes.json` in that folder to change the matching colors; replacing a photo does not automatically recolor the interface. The folder's README explains the fields. Missing photos fall back to the bundled artwork.

## 4. Plain writing and PDF views

AI requests now share selected plain-language principles from ASD-STE100 Issue 9: shorter sentences, consistent terms, active voice where the actor is known, and less stock phrasing. The rules preserve names, numbers, quotations, uncertainty, owners, and commitments. This is not full STE dictionary compliance.

Open a saved note or session and choose **Print / Save PDF**. For a session, select **Print / Save as PDF** again in the print view, then choose the browser's PDF destination. Session exports include active saved notes. The print view preserves saved content and makes no extra AI request. Clean and review notes before exporting when you want revised wording.

## 5. Larger recording uploads

The old 250 MB cap was an application limit. The default is now **2,048 MB**, adjustable in Settings from 250 to **4,096 MB**. The note editor displays the current limit.

Uploads stream into temporary files. Local faster-whisper processes audio in ten-minute sections to keep decoded audio memory bounded. Transcription jobs run in the background and are serialized to avoid loading concurrent jobs into the model. Files are removed when jobs finish or fail. Uploads remain local, regardless of the selected text AI provider.

Actual capacity depends on free temporary disk space and local transcription speed. Files above 250 MB require faster-whisper; the older Whisper backend retains its smaller limit. Increasing the limit does not make transcription faster. The new setting applies to recording uploads, not ordinary note attachments.

## 6. Record sound from any meeting app

Choose **Record a Meeting**, marked with a red circle, in the sidebar or on a session page. It opens the recorder on Spotter Live.

1. Send the meeting's sound to the Windows default playback device.
2. Choose the destination session. To add one here, select **+ Create a new session…**, enter its name, and select **Create session**. The new session is selected automatically without leaving Spotter Live. Leave **include my microphone** checked to capture your own voice too.
3. Start recording, then stop and save when the meeting ends.
4. Open the saved note and use **Clean/Compress Notes** to review the transcript.

The recorder uses Windows system audio capture and local transcription. The page explains the required local transcription setup and shows recorder status. It does not join the call as a bot.

In the desktop tray app, closing the window hides SKATE in the system tray and recording continues. The tray shows a skateboard when not recording and a red circle during capture. Hover for status, or right-click for **Open SKATE** and **Stop recording & save**. **Exit SKATE** shuts down the app and stops recording, so stop and save the meeting first. For source testing with the tray, use **Start SKATE.pyw**; **Start SKATE.bat** launches without a tray icon, so keep its SKATE window open. Restart the desktop app to load the new tray behavior. Packaged executables need a new build.

## 7. Info page: personality, hybrid memory, and human factors

The Info page now explains the headline as SKATE's deliberate attitude and personality: the decks, language, Spotter, GRIND, Lineup, and Landed actions. It describes the current capture-to-follow-through workflow, including the recording session dropdown, tray behavior, reviewed cleanup, larger uploads, and PDF views. Its board photos use the same customizable collection as Settings.

The memory explanation distinguishes the typed knowledge graph, semantic vector search, and keyword matching. The current implementation uses locally cached embeddings rather than a standalone vector database. Research links explain working memory, processing meaning at capture, cognitive load, and the neuroscience design analogy. Expandable sections hold technical detail and benchmark results, with their limits stated explicitly.

The retrieval benchmark was rerun on September 12: a relevant note ranked first on 9 of 10 author-labelled queries over 25 active demo notes. This is a keyword-only internal test, not a comparison against competing products or evidence of measured cognitive benefits.

## 8. Recording and transcription walkthrough

Info now has a **How to record & transcribe a meeting** button linking to `/about/recording`. The meeting recorder also links to this guide. It explains the Windows audio setup, existing/new sessions, recording status, stop-and-save processing, tray behavior, cleanup, imported recordings, and common problems. It distinguishes the PC recorder from the page-based room captions and documents local processing, optional cloud usage, and audio retention.

The guide states the application's free MIT license and includes a dated, sourced comparison with Granola. The benchmark section reports the existing internal retrieval result and long-text regression coverage. It attributes the website's “#1” wording as positioning rather than representing it as an established comparative ranking. Restart the source application to load the new route; packaged installations need an updated build.

## 9. Site facts and the Info mini skatepark

Info now leads with a wider headline and the website's actual 3D skateboard. It hops across a small Capture → Connect → Land stage, with Ollie, Kickflip, and Play/Pause controls. The pause preference is remembered; automatic motion starts paused for reduced-motion settings and stops when the stage is off screen or the page is hidden. Manual tricks remain available while automatic motion is paused.

The model, renderer, and fallback photo are bundled locally and load only on Info when the stage comes into view. The on-page Board credits disclosure was removed at the owner's request; bundled third-party notices remain with the assets. Existing board-photo themes remain in the side rails. The normal app build includes these static assets.

Quick fact cards highlight all seven quick-capture signals (pain, observation, action item, question, solution, recommendation, and insight), distinguish them from the 14 note types, and show three memory layers, free MIT licensing, and the measured 9/10 internal retrieval result. Signal labels and both capture counts come from the application's definitions. Added copy explains bounded evidence summaries, traceable recommendations, and the MCP tools' additive write boundary. The header now grows when navigation wraps at larger zoom.

## 10. Recoverable removal, saved API keys, and local cleanup

Trash buttons now appear on session cards, session headers, and individual notes within a session or on the note page. Confirmation states the scope and note count. Removed items move into the vault's private `.trash` folder and can be restored from the Trash page. Attachments remain in place for shared links and restoration. Restore refuses to overwrite a newer file. Active recording or transcription blocks removal of its destination session. Cached GRIND results cannot return removed note evidence, and installed-app seeding does not recreate demo files in Trash. An explicitly selected empty vault stays selected.

Settings has a Saved API keys section for OpenAI, Anthropic, OpenRouter, and ElevenLabs, visible even with No AI selected. Select the keys to remove and Save Settings. Blank password fields continue to preserve existing keys; removal takes priority over an autofilled replacement. Stored key values are never rendered into the page.

Local cleanup no longer treats the word “team” alone as work evidence. It screens sports catch-ups using nearby context, removes standalone filler, and keeps genuine work consequences or a matching workshop focus. Uncertain prose stays in an additional review section after the signals, rather than becoming the gist or a list of observations. No AI mode processes the retained transcript as a whole. The original-text attachment and review-before-apply workflow remain in place. These are local rules, not a semantic model; ambiguous topics still need review.

The installer release number is 1.2.0. Rebuild with Build Installer.bat to include these changes.

## 11. Long-note AI cleanup speed and progress

The complete-transcript cleanup previously waited for each 12,000-character section before sending the next. A long workshop could produce 14 sequential requests, each with a two-minute connection timeout. The elapsed timer did not report completed work. Local screening was quick; the serial AI requests caused the extra wait.

Cloud cleanup now runs up to three sections concurrently and merges the results in source order. This follows [OpenAI's latency guidance for independent steps](https://developers.openai.com/api/docs/guides/latency-optimization#parallelize). LM Studio stays at one request at a time. The selected provider, model, and reasoning setting are preserved. Both Clean/Compress Notes and Summarize Transcript show actual completed-section counts and offer **Stop cleanup**. Stopping closes the progress stream and prevents queued sections from being sent; requests already sent to the provider may still finish. The original remains in the editor until a reviewed result is applied.

Access, quota, and HTTP failures stop further queued AI calls. Repeated connection failures also switch the remaining sections to local extraction. The review reports which sections used local rules and gives a readable provider error without exposing credentials or response details. Existing cleanup API routes remain supported. These changes require restarting the source application or rebuilding and installing version 1.2.0; an already-running cleanup does not acquire the fix mid-request.

## 12. Clear graph overview as workshops grow

The GRIND opens All sessions with signals collapsed. The overview draws up to 80 notes at a time; Previous notes and Next notes browse larger collections. Headline counts still describe the complete selected scope, and the map reports exactly how many notes and signals it is showing.

Select a note and choose **Show signals** to explore its captured evidence in pages of 40. The side panel can filter by signal type and shows the full text when a signal is selected. **Hide signals** returns to the note overview. Search works in both 2D and 3D, searches the complete scoped graph, and jumps to the page containing the chosen note or signal. Session filtering always starts with signals collapsed. No notes, tags, or signals are deleted or capped in storage, search, or synthesis.

Layout calculations and drawing now use only the visible working set, including during startup. The map settles, then redraws for interactions and animation; active drawing is limited to approximately 30 frames per second, and hidden/offscreen maps skip drawing. Labels prioritize the selected or hovered item, with at most 20 labels on the overview. Fit uses the visible graph bounds. The filter row wraps at larger zoom, and the side panel moves below the map when its available width is narrow. The full scoped graph is still loaded once for search; initial loading continues to depend on vault size.

## 13. Recording status, tray controls, and retained audio

The tray follows the meeting recorder's state, checking twice per second: a skateboard when not recording, and a red circle during capture. Hover to see **Recording** with elapsed time, **Not recording**, transcription progress, **Audio & transcript saved**, or an error indication. Audio-capture warnings direct you back to SKATE to inspect the issue.

Right-click **Stop recording & save** to stop capture and begin local transcription without reopening the window. This uses the same stop-and-save operation as Spotter Live and is enabled only during capture. Simultaneous Stop clicks cannot start duplicate transcription jobs. Keep SKATE running until **Audio & transcript saved** appears.

Stopping now saves a permanent WAV in the chosen session's attachments before transcription begins. Local Whisper reads this saved file in ten-minute sections. The finished markdown transcript links to its audio; Spotter Live offers both links. If transcription fails, the WAV remains available for download and another attempt. Filenames are unique so later recordings do not overwrite previous audio. The mixed recording is mono, 16-bit, 16 kHz (about 115 MB per hour). This change applies to the PC meeting recorder; imported recordings still use temporary processing files. The Info page, recording guide, and recorder instructions explain the updated behavior. The desktop window now enables its normal Save dialog for attachment downloads; WebView2 previously canceled them by default.

## Verification

- All 111 automated tests passed, including the existing suite and 31 new regression tests. A simulated desktop close verifies that the window hides until Exit is requested. Session creation checks cover saved recording destinations, invalid names, and preservation of existing sessions.
- Browser checks covered the theme picker and persistence, light/dark graph views, sidebar height at 75%, 100%, and 140% zoom, cleanup review and source attachment, action rendering, recorder controls, and the session print view. The refreshed Info page was also checked in SKATE Original and Luna, including board images, expandable detail, and reading layout.
- Tests covered complete long-text processing, no-AI behavior, mocked AI responses and failures, streamed upload limits and cleanup, and real audio splitting with PyAV.
- After adding the walkthrough, all 31 September regression tests passed again. Browser checks covered the Info and recorder entry points, guide section anchors, troubleshooting disclosure, current upload-limit display, light/dark themes, and layout at 140% zoom without page overflow. No recording was started during guide verification.
- The Info skatepark was checked with the actual 3D model in the browser: Ollie and Kickflip, persisted pause, offscreen suspension, light/dark rendering, fact links, and 140% zoom. The header encloses wrapped navigation, and the board bundle does not load on the recording guide. Both new controller code and the copied renderer passed JavaScript syntax checks.
- After the Trash, credential-removal, and local-cleanup changes, all 129 tests passed, including 18 new checks using disposable vaults and fake keys. Checks cover restore conflicts, filesystem failure rollback, membership across shared folders, Unassigned notes, empty sessions, active recordings, seed preservation, and full long-transcript processing. Browser checks verified cancellation, note and session removal/restoration, removal of a fake OpenAI key in No AI mode, and exclusion of the nine-sentence Hurricanes conversation. New controls were inspected in light and dark themes and at 140% zoom.
- After the cleanup scheduling changes, all 138 tests passed. Nine added tests cover bounded concurrency, source-order merging, progress, cancellation, local-model serialization, provider failures, and sanitized streaming errors. A controlled 14-section simulation took 1.413 seconds sequentially and 0.508 seconds with three concurrent requests (about 2.8 times faster). This uses simulated provider responses, not a live OpenAI latency measurement.
- Browser checks on a disposable vault verified advancing progress on a 168,289-character synthetic note, stopping at 9 of 15 sections, and preservation of the editor text. Only the three already-running mock requests finished after Stop; the queued sections were not sent. A six-section cleanup and two-section transcript summary both opened their review successfully and restored the controls, with no browser JavaScript errors.
- Graph changes passed all 138 Python tests and eight JavaScript graph tests. The graph tests cover preservation and full paging of 910 signals, filtered pages, searching to the final signal, parent context, empty views, and a collection with 2,000 notes and 10,000 signals. Browser checks used 35 notes/910 signals, then 200 notes across 20 workshops, confirming the collapsed All sessions default, 80-note pages, 40-signal detail, final-page search, session resets, and light/dark layouts. The layout was checked at 140% zoom without page overflow, and rendered scripts passed syntax checks.
- Tray/audio changes passed all 149 Python tests and three new JavaScript recorder-control tests. Tests use synthetic audio, mocked transcription, and disposable vaults: idle/recording icon transitions, tooltips, menu enablement, concurrent Stop requests, saving audio before transcription, retained audio after failure, unique filenames, downloadable WAV bytes, and linked transcript notes. Existing desktop-window tests also verify downloads are enabled. A local preview passed a complete start/stop flow in the browser, transcription progress, separate saved links, note navigation, and rendered-script syntax checks without browser errors. Native Windows tray clicks and the native download dialog still need manual testing after rebuilding.
- Real meeting capture, multi-gigabyte recordings, speech-model accuracy, live cloud-model responses, and a rebuilt Windows installer were not exercised. The print view was inspected; an actual PDF file was not generated during these checks.
