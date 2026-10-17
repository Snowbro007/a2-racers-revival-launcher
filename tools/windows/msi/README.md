# Standard Windows Installer builder

Builds a normal per-user x64 MSI for **A2 Racers Revival**, using Python 3,
Windows Installer COM and the Windows built-in `makecab.exe`, with PowerShell 7
(`pwsh`) or Windows PowerShell to author the database. It never installs, starts
or uploads its payload. No external
installer toolchain is downloaded. No custom actions or security changes.

Use Python 3.10 or newer on 64-bit Windows. Invoke from this directory:

```powershell
python build_msi.py --payload "C:\build-input\installation-payload.zip" --icon "C:\build-input\a2-revival.ico" --output "C:\build-output\beta5-new" --version 0.1.5
```

Those four arguments are required. Optional `--powershell "C:\path\pwsh.exe"`
selects an existing PowerShell executable explicitly. Without it, the builder
prefers `pwsh` on PATH and then Windows PowerShell. The output directory must **not exist**, and
its parent must exist. A directory is claimed exclusively; previous builds are
never overwritten or deleted. Failed builds are retained for inspection; retry
with a new output directory. Payload and icon inputs are read-only and their
hashes are rechecked after authoring. Linked/junction/reparse-point ancestors,
device paths and traversal are rejected.

The ZIP must contain `A2 Racers Revival.exe` at its root and application files
under `app/`. File names must be portable ASCII Windows names. `app/local` and
`app/payload` are forbidden, including case variants. The builder rejects
unsafe paths, links, encryption, duplicates and file/directory collisions.
The caller must supply an authorized, game-free application payload.

Every generated file is inside the new output directory: `stage/`, source
staging, DDF, INF, cabinet/report, makecab log, build plan, result and MSI.
The DDF uses relative ASCII paths, so the surrounding output directory may
contain Unicode. No staging is written beside the ZIP or in the source tree.
The adjacent `write_database.ps1` must accompany the Python source. PowerShell
execution policy is not bypassed or changed.

The MSI defaults to `LocalAppDataFolder/A2 Racers Revival`, for the current
user. Full UI offers a PathEdit field and a standard folder browser, including
drive selection and new folders. The Install/Choose buttons validate the path
with `SetTargetPath`; cancelling the browser resets its changes. Choose a folder
where the current account can write. Basic/quiet MSI modes do not show a folder
picker. It requires x64 Windows and `NOT ALLUSERS`. Shortcuts target the native
launcher, with the supplied icon. Standard MSI product registration and actions
handle installation, repair, removal and major upgrades. There is no payload
execution after install and no wildcard/recursive user-data cleanup.

`HKCU\Software\A2 Racers Revival\Installer\InstallDir` records the selected
folder as an owned registry component. `AppSearch`/`RegLocator` searches this
64-bit directory value before costing in both MSI sequences. The installer
automatically avoids running AppSearch twice when full UI already ran it.
Major upgrades keep the previous folder and disable its edit/browse controls;
maintenance also has no path-change action. This avoids accidentally leaving
settings, imported games and cached components in a previous folder. Moving an
existing installation is not implemented. AppSearch uses the existing folder
when found, including for a quiet upgrade; it can override an `INSTALLDIR`
command-line value. Fresh quiet installs may supply `INSTALLDIR` explicitly.

Version `0.1.5` uses UpgradeCode
`{8630F56B-38D8-5D0E-A1C1-E17B6DC9C84D}` and ProductCode
`{4487EC10-5D13-5E01-9C91-CCBBAD2C4E8D}`, matching the reviewed beta5
candidate. Keep the namespace, UpgradeCode and component identifiers stable.
Raise the numeric three-part MSI version for later major upgrades. The
ProductCode changes per version; PackageCode changes per build. A rebuilt
MSI is a new artifact with a new hash and needs its own review. No attempt is
made to reproduce the byte hash of a previously built MSI.

Run the thirteen synthetic tests without building an MSI:

```powershell
python -m unittest discover -s . -p "test_msi_builder.py" -v
```

They test ZIP/path handling, per-user actions, version/component identity,
shortcuts, exclusive output allocation, link/device-path rejection, PowerShell
selection, folder
selection/validation/cancel events, prior-folder discovery and stable registry
ownership, dialog navigation, and a synthetic multi-block MSZIP cabinet.
Test fixtures remain under `test-output/`;
that directory and bytecode caches are excluded by `.gitignore`.

The folder-picker/error-dialog variant passed thirteen synthetic tests. The MSI authoring smoke
test built a 28,672-byte MSI from two synthetic sentinel files through the
explicitly selected bundled PowerShell 7. Windows PowerShell initially refused
the adjacent writer script because of its local execution policy. No policy was
changed or bypassed; the PS7 build also used ordinary `-File` execution. The
synthetic MSI was neither installed nor executed. The earlier
local candidate passed database/CAB/hash audits and read-only MSI engine
costing; this does not prove installation, UI, upgrade or uninstall behavior.
Those require separate Windows VM tests. No antivirus outcome is asserted.

Authoring references: Microsoft's [Browse Dialog](https://learn.microsoft.com/en-us/windows/win32/msi/browse-dialog),
[SetTargetPath](https://learn.microsoft.com/en-us/windows/win32/msi/settargetpath-controlevent),
[Reset](https://learn.microsoft.com/en-us/windows/win32/msi/reset-controlevent),
[AppSearch action](https://learn.microsoft.com/en-us/windows/win32/msi/appsearch-action),
[AppSearch table](https://learn.microsoft.com/en-us/windows/win32/msi/appsearch-table),
and [RegLocator table](https://learn.microsoft.com/en-us/windows/win32/msi/reglocator-table).
No WiX source, toolchain or binary is required by this builder.

Public source files: `build_msi.py`, `write_database.ps1`, `cab_codec.py`,
`test_msi_builder.py`, `README.md`, `.gitignore`. Do not publish caches,
test-output directories, generated inputs or personal build reports.

## Windows Installer lifecycle check

From the repository root, `python tools/windows/msi/verify_lifecycle.py
--output local/installer-validation/my-unique-run --execute` authors two tiny
MSIs with a random test product identity. The required `.exe` filename contains
plain text, not machine code. This test never executes a launcher or game.
It installs in a chosen folder containing spaces and Unicode, verifies the two
shortcut targets and exact icon bytes, upgrades without specifying the folder
again, refuses a downgrade, repairs an owned file, and uninstalls. Synthetic
settings, progress and cache files must survive unchanged. The test registry
keys, product GUIDs and shortcuts are isolated from actual A2 installations.
Without `--execute`, it only builds and audits the two synthetic MSI databases.

On 17 October 2026, this lifecycle passed locally and on a clean GitHub-hosted
Windows runner: [run 39051596665](https://github.com/Snowbro007/a2-racers-revival-launcher/actions/runs/39051596665).
This verifies the installer engine path with text fixtures. It does not verify
interactive folder-picker behavior, the full installed launcher, game starts,
SmartScreen or antivirus acceptance. The native test helper remains disabled.
`read_test_shortcuts.ps1` is the read-only shortcut inspector used by this test.
The release workflow requires successful lifecycle evidence before it creates
a draft release. New public releases still need their own exact-file review.
