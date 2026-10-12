import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_background/flutter_background.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    return control.type == 'NexTradeBackground'
        ? NexTradeBackgroundService(control: control)
        : null;
  }
}

class NexTradeBackgroundService extends FletService {
  NexTradeBackgroundService({required super.control});

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    // A disposed Python session must not leave a misleading running indicator.
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android &&
        FlutterBackground.isBackgroundExecutionEnabled) {
      FlutterBackground.disableBackgroundExecution();
    }
    super.dispose();
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) return false;
    switch (name) {
      case 'start':
        if (FlutterBackground.isBackgroundExecutionEnabled) return true;
        final initialized = await FlutterBackground.initialize(
          androidConfig: const FlutterBackgroundAndroidConfig(
            notificationTitle: 'NexTrade — skaner EURC',
            notificationText: 'Monitorowanie włączone. Otwórz aplikację, aby zatrzymać.',
            notificationIcon: AndroidResource(name: 'ic_nextrade_monitor'),
            notificationImportance: AndroidNotificationImportance.normal,
            enableWifiLock: true,
            showBadge: false,
            shouldRequestBatteryOptimizationsOff: true,
          ),
        );
        if (!initialized) return false;
        final started = await FlutterBackground.enableBackgroundExecution();
        if (!started) await FlutterBackground.disableBackgroundExecution();
        return started;
      case 'stop':
        if (FlutterBackground.isBackgroundExecutionEnabled) {
          await FlutterBackground.disableBackgroundExecution();
        }
        return true;
      case 'is_enabled':
        return FlutterBackground.isBackgroundExecutionEnabled &&
            await FlutterBackground.hasPermissions;
      default:
        throw ArgumentError('Unknown background method: $name');
    }
  }
}
