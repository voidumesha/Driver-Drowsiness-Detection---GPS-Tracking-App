import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';

class AlertService {
  static Stream<QuerySnapshot<Map<String, dynamic>>> getAlerts() {
    return FirebaseFirestore.instance
        .collection('alerts')
        .where('isActive', isEqualTo: true)
        .orderBy('timestamp', descending: true)
        .limit(10)
        .snapshots();
  }

  static Future<void> dismissAlert(String alertId) async {
    await FirebaseFirestore.instance
        .collection('alerts')
        .doc(alertId)
        .update({'isActive': false});
  }
} 