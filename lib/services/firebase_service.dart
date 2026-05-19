import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';

class FirebaseService {
  static final FirebaseService _instance = FirebaseService._internal();
  factory FirebaseService() => _instance;

  FirebaseService._internal();

  Future<void> initialize() async {
    try {
      await Firebase.initializeApp();
      
      final messaging = FirebaseMessaging.instance;

      // Subscribe to backend topic
      await messaging.subscribeToTopic('crisis_alerts');

      // Request permission
      NotificationSettings settings = await messaging.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );

      if (settings.authorizationStatus == AuthorizationStatus.authorized) {
        if (kDebugMode) {
          print('User granted permission and subscribed to crisis_alerts');
        }
        
        // Listen for foreground messages
        FirebaseMessaging.onMessage.listen((RemoteMessage message) {
          if (kDebugMode) {
            print('Got a message whilst in the foreground!');
          }
        });

        // Set background handler
        FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);
      }
    } catch (e) {
      if (kDebugMode) {
        print('Firebase initialization failed: $e');
      }
    }
  }
}

@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
  if (kDebugMode) {
    print("Handling a background message: ${message.messageId}");
  }
}
