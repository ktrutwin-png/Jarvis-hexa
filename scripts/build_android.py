"""Build with pinned Flet, applying native Android settings before Gradle runs.

Flet 1.0.4 has no pre-Gradle hook for service declarations/desugaring. This
subclass uses its normal packaging pipeline and customizes only run_flutter.
No failed build is ignored or treated as a successful APK.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

import flet.version
import flet_cli.commands.build
from flet_android_notifications.patcher import patch_gradle_file

ANDROID = "http://schemas.android.com/apk/res/android"
A = "{" + ANDROID + "}"


def configure_android(project: Path) -> None:
    manifest_path = project / "android/app/src/main/AndroidManifest.xml"
    tree = ET.parse(manifest_path)
    app = tree.getroot().find("application")
    if app is None:
        raise RuntimeError("Generated Android application is missing")
    service_name = "de.julianassmann.flutter_background.IsolateHolderService"
    service = next((s for s in app.findall("service")
                    if s.get(A + "name") == service_name), None)
    if service is None:
        service = ET.SubElement(app, "service", {A + "name": service_name})
    service.set(A + "exported", "false")
    service.set(A + "stopWithTask", "false")
    service.set(A + "foregroundServiceType", "specialUse")
    subtype_name = "android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
    subtype = next((p for p in service.findall("property")
                    if p.get(A + "name") == subtype_name), None)
    if subtype is None:
        subtype = ET.SubElement(service, "property", {A + "name": subtype_name})
    subtype.set(A + "value", "User-started continuous crypto market analysis on device "
                "with time-sensitive proposal alerts and an explicit stop control")
    receiver_name = "com.dexterous.flutterlocalnotifications.ActionBroadcastReceiver"
    if not any(r.get(A + "name") == receiver_name for r in app.findall("receiver")):
        ET.SubElement(app, "receiver", {A + "name": receiver_name, A + "exported": "false"})
    ET.register_namespace("android", ANDROID)
    ET.register_namespace("tools", "http://schemas.android.com/tools")
    ET.indent(tree, space="    ")
    tree.write(manifest_path, encoding="utf-8", xml_declaration=True)
    patch_gradle_file(project / "android/app/build.gradle.kts")
    drawable = project / "android/app/src/main/res/drawable"
    drawable.mkdir(parents=True, exist_ok=True)
    (drawable / "ic_nextrade_monitor.xml").write_text(
        '<vector xmlns:android="http://schemas.android.com/apk/res/android" '
        'android:width="24dp" android:height="24dp" '
        'android:viewportWidth="24" android:viewportHeight="24">'
        '<path android:strokeColor="#FFFFFFFF" android:strokeWidth="2" '
        'android:fillColor="#00000000" android:pathData="M3,18 L8,12 L12,15 L21,5"/>'
        '</vector>', encoding="utf-8")
    raw = drawable.parent / "raw"
    raw.mkdir(exist_ok=True)
    (raw / "nextrade_keep.xml").write_text(
        '<resources xmlns:tools="http://schemas.android.com/tools" '
        'tools:keep="@drawable/ic_nextrade_monitor"/>', encoding="utf-8")


class AndroidBuild(flet_cli.commands.build.Command):
    def run_flutter(self):
        if self.target_platform not in {"apk", "aab"}:
            raise RuntimeError("This wrapper only supports Android builds")
        configure_android(Path(self.flutter_dir))
        super().run_flutter()


if __name__ == "__main__":
    if flet.version.flet_version != "1.0.4":
        raise SystemExit("Review the native build hook before changing Flet 1.0.4")
    flet_cli.commands.build.Command = AndroidBuild
    from flet_cli.cli import main
    main()
