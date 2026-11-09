# Troubleshooting

The log file is in `%LOCALAPPDATA%\TatumGames\tg_sales\logs\tg_sales.log`
(contact details are redacted). The database server's own log is in
`%LOCALAPPDATA%\TatumGames\tg_sales\postgres\server.log`.

| Problem | What to do |
|---------|-----------|
| "TG Sales CRM is not set up on this computer yet" | You started `launch.bat` from source without setup, or the release ZIP was not fully extracted. Extract the whole ZIP again (or run `setup.bat` for source checkouts). |
| "The PostgreSQL database programs were not found" | The `runtime\postgresql` folder is missing: extract the complete release ZIP again. |
| "Another program is already using port 54329" | Another program uses tg_sales's database port. Close it or restart Windows. |
| The browser does not open | Open `http://127.0.0.1:8765` yourself (the tg_sales window shows the exact address). |
| "TG Sales CRM is already running" | It is running in another window; the browser opens at it. To restart, run `stop.bat` first. |
| "tg_sales is not responding" in the browser | The tg_sales window was closed. Start `launch.bat` again. |
| Windows "protected your PC" (SmartScreen) | The program is not code-signed yet. Check the ZIP's SHA-256 against `SHA256SUMS.txt` from the official release, then "More info" › "Run anyway". Do not disable Windows security. |
| Antivirus quarantines `tg_sales.exe` | A false positive is possible for unsigned programs built with PyInstaller. Restore the file, add an exception for the tg_sales folder if your IT allows it, and report it to your support contact. |
| "This tg_sales database was created by a newer version" | Install the latest release; older versions cannot open newer databases. |
| "The database could not be upgraded" | Nothing was changed and a backup was saved. Send the log to your support contact. |
| Game discovery shows "Offline" or errors | Discovery needs the internet; everything else works offline. Earlier results stay available and are marked when they may be out of date. If Steam limits requests, wait a few minutes. |
| An import says the file cannot be read | Save the spreadsheet as `.xlsx` or CSV (UTF-8) with one header row; macro-enabled (`.xlsm`) and old `.xls` files are refused for safety. |
| My logo does not appear | Upload it in **Settings › Branding** (copying a file into the project's `assets` folder does nothing). Use PNG, JPEG, WebP or BMP up to 5 MB, or an SVG without scripts or external links. Reload the page; if it still does not show, the upload message says why the image was refused. |
| A field is missing from the import column list | Choose **+ Create custom field…** in the list, or create it in Settings › Custom fields. Archived custom fields are hidden: restore them there. |
| "Only one column can be mapped to …" | Two columns were given the same field. Choose another field, or *Don't import*, for one of them. |
| Review dates or source URLs were left empty | Read the warnings in the import result: dates like 04/03/2026 need a date order, and addresses must start with `http://` or `https://` (or be a plain domain). Correct the file and import again, or edit the prospect. |
| A new lane is not visible | Check that it is not archived (Settings › Sales lanes) and reload the page. New opportunities can only use active lanes; archived lanes with records still appear on the Pipeline tabs. |
| A lane cannot be deleted | It still has opportunities or lane-specific stages. Use **Move records** to move them to another lane first, or **Archive** the lane instead. |
| A sync package is refused | Read the message: wrong passphrase, damaged or changed file, different tg_sales version, or exported from this computer. Ask for a new package made with the same release. |
| Restore is not offered | Restore needs the database administrator account, which the local install has; on Docker or hosted setups set `TG_SALES_ADMIN_DATABASE_URL`. You can always download backups. |
| Disk full | Backups, imports and reports stop with a message and change nothing. Free space (old backups can be deleted in Settings › Backups) and try again. |
| Something else | Settings & Sync › About › "Check database health", then send the log file to your support contact. |

## Starting completely fresh (testing only)

Stop tg_sales, then move `%LOCALAPPDATA%\TatumGames\tg_sales` elsewhere (do not
delete it unless you are sure). The next start creates a new empty database.
