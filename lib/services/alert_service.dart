import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

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

  static Future<void> updateBreakStatus(bool isBreaking) async {
    try {
      // Get current break count
      DocumentSnapshot breakDoc = await FirebaseFirestore.instance
          .collection('breaking')
          .doc('status')
          .get();

      int currentCount = 0;
      if (breakDoc.exists) {
        currentCount = (breakDoc.data() as Map<String, dynamic>)['breakCount'] ?? 0;
      }

      // Update break status with incremented count
      await FirebaseFirestore.instance
          .collection('breaking')
          .doc('status')
          .set({
        'isBreaking': isBreaking,
        'timestamp': FieldValue.serverTimestamp(),
        'breakCount': isBreaking ? currentCount + 1 : currentCount,
      }, SetOptions(merge: true));

      // Update active journey
      if (isBreaking) {
        QuerySnapshot activeJourneys = await FirebaseFirestore.instance
            .collection('journeys')
            .where('isActive', isEqualTo: true)
            .get();

        for (var doc in activeJourneys.docs) {
          await doc.reference.update({
            'totalBreaks': currentCount + 1,  // Use breakCount from breaking/status
            'breaks': FieldValue.arrayUnion([
              {
                'time': FieldValue.serverTimestamp(),
                'location': {
                  'latitude': doc.get('lastLocation')['latitude'],
                  'longitude': doc.get('lastLocation')['longitude'],
                },
                'duration': 20
              }
            ])
          });
        }
      }
    } catch (e) {
      print('Error updating break status: $e');
    }
  }

  static Stream<DocumentSnapshot> getBreakStatus() {
    return FirebaseFirestore.instance
        .collection('breaking')
        .doc('status')
        .snapshots();
  }

  static Stream<List<String>> getNearbyPlaces(double lat, double lng) {
    return FirebaseFirestore.instance.collection('cities').snapshots().map(
        (snapshot) =>
            snapshot.docs.map((doc) => doc.data()['name'] as String).toList());
  }

  static Future<List<String>> getNearbyCity(double lat, double lng) async {
    try {
      // Check if current location is near any city (within 2km radius)
      QuerySnapshot cityDocs =
          await FirebaseFirestore.instance.collection('cities').get();

      List<String> nearbyCities = [];

      for (var doc in cityDocs.docs) {
        Map<String, dynamic> cityData = doc.data() as Map<String, dynamic>;
        double cityLat = cityData['location']['latitude'];
        double cityLng = cityData['location']['longitude'];

        // Calculate distance to city
        double distance =
            Geolocator.distanceBetween(lat, lng, cityLat, cityLng);

        // If within 2km, add to nearby cities
        if (distance <= 2000) {
          // 2km in meters
          nearbyCities.add(cityData['name']);
        }
      }

      return nearbyCities;
    } catch (e) {
      print('Error getting nearby cities: $e');
      return [];
    }
  }
}
