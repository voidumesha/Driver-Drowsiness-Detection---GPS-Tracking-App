import 'package:geolocator/geolocator.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

class LocationService {
  final FirebaseFirestore _firestore = FirebaseFirestore.instance;
  bool _isTracking = false;
  Stream<Position>? _positionStream;
  Function(Position)? onLocationUpdate;
  Position? _currentPosition;

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

    _currentPosition = await Geolocator.getCurrentPosition();
    return _currentPosition!;
  }

  Future<void> updateLocation(bool isStarting, {LatLng? destination}) async {
    if (_currentPosition == null) {
      _currentPosition = await getCurrentLocation();
    }

    if (isStarting && !_isTracking) {
      // Get the distance from Google Directions API
      if (destination != null) {
        try {
          final String apiKey = 'AIzaSyDrQkjLbhOQRTmYTGmti785_MPrJFAj99w';
          final String url =
              'https://maps.googleapis.com/maps/api/directions/json?origin=${_currentPosition!.latitude},${_currentPosition!.longitude}'
              '&destination=${destination.latitude},${destination.longitude}&key=$apiKey';

          final response = await http.get(Uri.parse(url));
          final data = json.decode(response.body);

          if (data['status'] == 'OK') {
            final distance = data['routes'][0]['legs'][0]['distance']['text'];
            // Parse distance removing 'km' and convert to double
            final distanceValue =
                double.parse(distance.replaceAll(RegExp(r'[^0-9.]'), ''));

            DocumentReference journeyRef =
                await _firestore.collection('journeys').add({
              'startTime': FieldValue.serverTimestamp(),
              'startLocation': {
                'latitude': _currentPosition!.latitude,
                'longitude': _currentPosition!.longitude,
              },
              'destination': {
                'latitude': destination.latitude,
                'longitude': destination.longitude
              },
              'distance': distanceValue, // Use Google's calculated distance
              'isActive': true,
              'breaks': [],
              'totalBreaks': 0,  // Initialize break count
              'alertLocations': [],
            });

            _positionStream = Geolocator.getPositionStream(
              locationSettings: const LocationSettings(
                accuracy: LocationAccuracy.high,
                distanceFilter: 2,
              ),
            );

            _positionStream!.listen((Position position) async {
              _currentPosition = position;
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
          }
        } catch (e) {
          print('Error calculating distance: $e');
        }
      }
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
          'endLocation': {
            'latitude': _currentPosition!.latitude,
            'longitude': _currentPosition!.longitude,
          },
          'completed': true,
          'completedAt': FieldValue.serverTimestamp(),
        });
      }

      DocumentSnapshot breakStatus =
          await _firestore.collection('breaking').doc('status').get();

      if (breakStatus.exists && breakStatus.get('isBreaking')) {
        await _firestore
            .collection('breaking')
            .doc('status')
            .update({'isBreaking': false});
      }
    }
  }

  bool get isTracking => _isTracking;
}
