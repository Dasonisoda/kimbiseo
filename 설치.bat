@echo off
rem Kim-Biseo installer: opens the install window (no console). Double-click this file.
rem If the zip was not extracted first, installer\install.ps1 is missing: show a message (Korean, encoded) and stop.
if not exist "%~dp0installer\install.ps1" (
  start "" powershell.exe -NoProfile -WindowStyle Hidden -EncodedCommand QQBkAGQALQBUAHkAcABlACAALQBBAHMAcwBlAG0AYgBsAHkATgBhAG0AZQAgAFMAeQBzAHQAZQBtAC4AVwBpAG4AZABvAHcAcwAuAEYAbwByAG0AcwA7ACAAWwBXAGkAbgBkAG8AdwBzAC4ARgBvAHIAbQBzAC4ATQBlAHMAcwBhAGcAZQBCAG8AeABdADoAOgBTAGgAbwB3ACgAIgBVxZXNRMcgADy6AMggAIDUtMUgAPzIOMGUxi4ADQAKAA0ACgAbvEDHIAB6AGkAcAAgAAzTfMdExyAAJMZ4ub3KIAB00K25IACSISAAJwCoulC0IABVxZXNIACA1DCuJwAgAJIhIACA1LC5IAD001SzIABIxVjHIAAnACTBWM4uAGIAYQB0ACcAIABExyAAULQgAIi8IAAMsuy3IAD8yDjBlMYuACIALAAgACcAQK5EvhzBIAAkwVjOJwApACAAfAAgAE8AdQB0AC0ATgB1AGwAbAA=
  exit /b 1
)
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0installer\install.ps1"
