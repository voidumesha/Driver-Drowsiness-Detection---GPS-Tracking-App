import 'package:geolocator/geolocator.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';

class LocationService {
  final FirebaseFirestore _firestore = FirebaseFirestore.instance;
  bool _isTracking = false;
  Stream<Position>? _positionStream;
  Function(Position)? onLocationUpdate;

  Future<Position> getCurrentLocation() async {
    bool serviceEnabled;
    LocationPermission permission;

    // Test if location services are enabled.
    serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      throw 'Location services are disabled.';
    }

    permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        throw 'Location permissions are denied';
      }
    }

    if (permission == LocationPermission.deniedForever) {
      throw 'Location permissions are permanently denied, we cannot request permissions.';
    }

    return await Geolocator.getCurrentPosition();
  }

  Future<void> updateLocation(bool isStarting, {LatLng? destination}) async {
    if (isStarting && !_isTracking) {
      DocumentReference journeyRef =
          await _firestore.collection('journeys').add({
        'startTime': FieldValue.serverTimestamp(),
        'isActive': true,
        'destination': destination != null
            ? {
                'latitude': destination.latitude,
                'longitude': destination.longitude
              }
            : null,
      });

      _positionStream = Geolocator.getPositionStream(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.high,
          distanceFilter: 2,
        ),
      );

      _positionStream!.listen((Position position) async {
        // Notify listeners about location update
        onLocationUpdate?.call(position);

        await journeyRef.collection('locations').add({
          'latitude': position.latitude,
          'longitude': position.longitude,
          'timestamp': FieldValue.serverTimestamp(),
          'speed': position.speed,
          'accuracy': position.accuracy,
          'heading': position.heading,
        });

        await journeyRef.update({
          'lastLocation': {
            'latitude': position.latitude,
            'longitude': position.longitude,
            'timestamp': FieldValue.serverTimestamp(),
            'heading': position.heading,
          }
        });
      });

      _isTracking = true;
    } else if (!isStarting && _isTracking) {
      _positionStream = null;
      _isTracking = false;

      QuerySnapshot activeJourneys = await _firestore
          .collection('journeys')
          .where('isActive', isEqualTo: true)
          .get();

      for (var doc in activeJourneys.docs) {
        await doc.reference.update({
          'isActive': false,
          'endTime': FieldValue.serverTimestamp(),
        });
      }
    }
  }

  bool get isTracking => _isTracking;
}
