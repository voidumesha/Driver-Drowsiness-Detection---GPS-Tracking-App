import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:geolocator/geolocator.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import '../services/location_service.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'admin_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/alert_service.dart';
import 'dart:async';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class PlaceSuggestion {
  final String description;
  final String placeId;

  PlaceSuggestion({required this.description, required this.placeId});
}

class _HomeScreenState extends State<HomeScreen> {
  final LocationService _locationService = LocationService();
  GoogleMapController? _mapController;
  Position? _currentPosition;
  Set<Marker> _markers = {};
  Set<Polyline> _polylines = {};
  TextEditingController _destinationController = TextEditingController();
  LatLng? _destinationLatLng;
  double? _distance;
  List<PlaceSuggestion> _suggestions = [];
  bool _showSuggestions = false;
  bool _isRouteInitialized = false;
  Timer? _breakTimer;
  int _remainingBreakTime = 20 * 60; // 20 minutes in seconds
  LatLng? _breakLocation;

  @override
  void initState() {
    super.initState();
    _getCurrentLocation();
    _restorePreviousRoute();
    _setupLocationUpdates();
    _listenToAlerts();
    _listenToBreakStatus();
  }

  void _setupLocationUpdates() {
    _locationService.onLocationUpdate = (Position position) {
      setState(() {
        _currentPosition = position;
      });

      if (_destinationLatLng != null) {
        _getDirections();
      }
    };
  }

  Future<void> _getCurrentLocation() async {
    try {
      Position position = await _locationService.getCurrentLocation();
      setState(() {
        _currentPosition = position;
        // Remove the initial marker since we don't want it
      });

      _mapController?.animateCamera(
        CameraUpdate.newCameraPosition(
          CameraPosition(
            target: LatLng(position.latitude, position.longitude),
            zoom: 15,
          ),
        ),
      );
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(e.toString())),
      );
    }
  }

  Future<void> _getDirections() async {
    if (_currentPosition == null || _destinationLatLng == null) return;

    final String apiKey = 'AIzaSyDrQkjLbhOQRTmYTGmti785_MPrJFAj99w';
    final String baseUrl =
        'https://maps.googleapis.com/maps/api/directions/json';
    final String url =
        '$baseUrl?origin=${_currentPosition!.latitude},${_currentPosition!.longitude}'
        '&destination=${_destinationLatLng!.latitude},${_destinationLatLng!.longitude}'
        '&key=$apiKey';

    try {
      final response = await http.get(Uri.parse(url));
      final data = json.decode(response.body);

      if (data['status'] == 'OK') {
        final points =
            _decodePolyline(data['routes'][0]['overview_polyline']['points']);
        final distance = data['routes'][0]['legs'][0]['distance']['text'];

        setState(() {
          _polylines.clear();
          _polylines.add(
            Polyline(
              polylineId: const PolylineId('route'),
              points: points,
              color: Colors.blue,
              width: 5,
            ),
          );

          _markers.clear();
          if (_destinationLatLng != null) {
            _markers.add(
              Marker(
                markerId: const MarkerId('destination'),
                position: _destinationLatLng!,
                infoWindow: InfoWindow(title: _destinationController.text),
              ),
            );
          }

          _distance =
              double.tryParse(distance.replaceAll(RegExp(r'[^0-9.]'), ''));
        });

        // Only adjust camera on initial route setup, not during updates
        if (!_isRouteInitialized) {
          LatLngBounds bounds = LatLngBounds(
            southwest: LatLng(
              points.map((p) => p.latitude).reduce((a, b) => a < b ? a : b),
              points.map((p) => p.longitude).reduce((a, b) => a < b ? a : b),
            ),
            northeast: LatLng(
              points.map((p) => p.latitude).reduce((a, b) => a > b ? a : b),
              points.map((p) => p.longitude).reduce((a, b) => a > b ? a : b),
            ),
          );
          _mapController
              ?.animateCamera(CameraUpdate.newLatLngBounds(bounds, 100));
          _isRouteInitialized = true;
        }
      }
    } catch (e) {
      print('Error getting directions: $e');
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error getting directions: $e')),
      );
    }
  }

  List<LatLng> _decodePolyline(String encoded) {
    List<LatLng> points = [];
    int index = 0, len = encoded.length;
    int lat = 0, lng = 0;

    while (index < len) {
      int b, shift = 0, result = 0;
      do {
        b = encoded.codeUnitAt(index++) - 63;
        result |= (b & 0x1F) << shift;
        shift += 5;
      } while (b >= 0x20);
      int dlat = ((result & 1) != 0 ? ~(result >> 1) : (result >> 1));
      lat += dlat;

      shift = 0;
      result = 0;
      do {
        b = encoded.codeUnitAt(index++) - 63;
        result |= (b & 0x1F) << shift;
        shift += 5;
      } while (b >= 0x20);
      int dlng = ((result & 1) != 0 ? ~(result >> 1) : (result >> 1));
      lng += dlng;

      points.add(LatLng(lat / 1E5, lng / 1E5));
    }
    return points;
  }

  Future<void> _getPlaceSuggestions(String input) async {
    if (input.isEmpty) {
      setState(() {
        _suggestions = [];
        _showSuggestions = false;
      });
      return;
    }

    final String apiKey = 'AIzaSyDrQkjLbhOQRTmYTGmti785_MPrJFAj99w';
    final String baseUrl =
        'https://maps.googleapis.com/maps/api/place/autocomplete/json';
    final String url =
        '$baseUrl?input=${Uri.encodeComponent(input)}&key=$apiKey';

    try {
      final response = await http.get(Uri.parse(url));
      final data = json.decode(response.body);

      if (data['status'] == 'OK') {
        setState(() {
          _suggestions = (data['predictions'] as List)
              .map((prediction) => PlaceSuggestion(
                    description: prediction['description'],
                    placeId: prediction['place_id'],
                  ))
              .toList();
          _showSuggestions = true;
        });
      }
    } catch (e) {
      print('Error getting place suggestions: $e');
    }
  }

  Future<void> _searchLocation() async {
    if (_destinationController.text.isEmpty) return;
    _isRouteInitialized = false;
    final String apiKey = 'AIzaSyDrQkjLbhOQRTmYTGmti785_MPrJFAj99w';
    final String baseUrl = 'https://maps.googleapis.com/maps/api/geocode/json';
    final String url =
        '$baseUrl?address=${Uri.encodeComponent(_destinationController.text)}&key=$apiKey';

    try {
      final response = await http.get(Uri.parse(url));
      final data = json.decode(response.body);

      if (data['status'] == 'OK') {
        final location = data['results'][0]['geometry']['location'];
        setState(() {
          _destinationLatLng = LatLng(location['lat'], location['lng']);
        });
        await _getDirections(); // Get directions immediately after setting destination
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Error searching location: $e')),
      );
    }
  }

  Future<void> _handleStartStop(bool isStarting) async {
    try {
      if (isStarting) {
        // Check if destination is set
        if (_destinationLatLng == null) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Please enter a destination first'),
              backgroundColor: Colors.orange,
            ),
          );
          return;
        }

        // Start journey
        await _locationService.updateLocation(true,
            destination: _destinationLatLng);

        // Show success message
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Row(
                children: [
                  const Icon(Icons.directions_car, color: Colors.white),
                  const SizedBox(width: 8),
                  Text('Journey started to ${_destinationController.text}'),
                ],
              ),
              backgroundColor: Colors.green,
              duration: const Duration(seconds: 3),
            ),
          );
        }
      } else {
        // Stop journey
        await _locationService.updateLocation(false);

        // Clear map and show completion message
        setState(() {
          _markers.clear();
          _polylines.clear();
          _destinationLatLng = null;
          _destinationController.clear();
          _distance = null;
        });

        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Journey completed and saved to reports'),
              backgroundColor: Colors.blue,
              duration: Duration(seconds: 3),
            ),
          );
        }
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: ${e.toString()}'),
            backgroundColor: Colors.red,
          ),
        );
      }
    }
  }

  Future<void> _restorePreviousRoute() async {
    final prefs = await SharedPreferences.getInstance();
    double? destLat = prefs.getDouble('dest_lat');
    double? destLng = prefs.getDouble('dest_lng');
    String? destAddress = prefs.getString('dest_address');

    if (destLat != null && destLng != null && destAddress != null) {
      setState(() {
        _destinationLatLng = LatLng(destLat, destLng);
        _destinationController.text = destAddress;
      });
      await _getDirections();
    }
  }

  void _showDrowsinessAlert(String message) {
    if (!mounted) return;

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red,
        duration: const Duration(seconds: 5),
        action: SnackBarAction(
          label: 'DISMISS',
          textColor: Colors.white,
          onPressed: () {
            if (!mounted) return;
            ScaffoldMessenger.of(context).hideCurrentSnackBar();
          },
        ),
      ),
    );
  }

  void _listenToAlerts() {
    AlertService.getAlerts().listen((snapshot) {
      try {
        if (snapshot.docs.isNotEmpty) {
          for (var doc in snapshot.docs) {
            final data = doc.data();
            final message = data['message'];
            if (message != null && mounted) {
              _showDrowsinessAlert(message.toString());
              AlertService.dismissAlert(doc.id);
            }
          }
        }
      } catch (e) {
        print('Error processing alert: $e');
      }
    }, onError: (error) {
      print('Error listening to alerts: $error');
    });
  }

  void _listenToBreakStatus() {
    AlertService.getBreakStatus().listen((snapshot) {
      if (snapshot.exists) {
        final data = snapshot.data() as Map<String, dynamic>;
        final isBreaking = data['isBreaking'] as bool;

        setState(() {
          if (isBreaking) {
            // Start or resume break timer
            _remainingBreakTime = 1 * 60; // Reset to 20 minutes
            _startBreakTimer();

            // Show break notification
            ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(
                content: Text('Break time started - 20 minutes'),
                backgroundColor: Colors.orange,
              ),
            );
          } else {
            // Cancel timer if break is over
            _breakTimer?.cancel();
            _breakTimer = null;
            _remainingBreakTime = 0;
          }
        });
      }
    });
  }

  void _startBreakTimer() {
    _breakTimer?.cancel(); // Cancel any existing timer
    _breakTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      setState(() {
        if (_remainingBreakTime > 0) {
          _remainingBreakTime--;
        } else {
          _breakTimer?.cancel();
          _breakTimer = null;
          AlertService.updateBreakStatus(false);
        }
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Driver Tracking'),
        actions: [
          StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
            stream: AlertService.getAlerts(),
            builder: (context, snapshot) {
              if (snapshot.hasData && snapshot.data!.docs.isNotEmpty) {
                return IconButton(
                  icon: const Icon(Icons.warning, color: Colors.red),
                  onPressed: () {
                    // Show alert details if needed
                  },
                );
              }
              return const SizedBox.shrink();
            },
          ),
          IconButton(
            icon: const Icon(Icons.admin_panel_settings),
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (context) => const AdminScreen(),
                ),
              );
            },
          ),
        ],
      ),
      body: SingleChildScrollView(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.all(8.0),
              child: Column(
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _destinationController,
                          decoration: const InputDecoration(
                            labelText: 'Enter Destination',
                            border: OutlineInputBorder(),
                          ),
                          onChanged: _getPlaceSuggestions,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.search),
                        onPressed: _searchLocation,
                      ),
                    ],
                  ),
                  if (_showSuggestions && _suggestions.isNotEmpty)
                    Container(
                      color: Colors.white,
                      child: ListView.builder(
                        shrinkWrap: true,
                        itemCount: _suggestions.length,
                        itemBuilder: (context, index) {
                          return ListTile(
                            title: Text(_suggestions[index].description),
                            onTap: () {
                              setState(() {
                                _destinationController.text =
                                    _suggestions[index].description;
                                _showSuggestions = false;
                              });
                              _searchLocation();
                            },
                          );
                        },
                      ),
                    ),
                ],
              ),
            ),
            if (_distance != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8.0),
                child: Text(
                  'Distance: ${_distance!.toStringAsFixed(2)} km',
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.bold),
                ),
              ),
            if (_breakTimer != null)
              Padding(
                padding: const EdgeInsets.all(8.0),
                child: Card(
                  color: Colors.orange[100],
                  child: Padding(
                    padding: const EdgeInsets.all(16.0),
                    child: Column(
                      children: [
                        const Text(
                          'Rest Time Remaining:',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                        Text(
                          '${_remainingBreakTime ~/ 60}:${(_remainingBreakTime % 60).toString().padLeft(2, '0')}',
                          style: const TextStyle(
                            fontSize: 24,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            SizedBox(
              height: MediaQuery.of(context).size.height * 0.6,
              child: _currentPosition == null
                  ? const Center(child: CircularProgressIndicator())
                  : GoogleMap(
                      initialCameraPosition: CameraPosition(
                        target: LatLng(
                          _currentPosition!.latitude,
                          _currentPosition!.longitude,
                        ),
                        zoom: 15,
                      ),
                      onMapCreated: (controller) => _mapController = controller,
                      markers: _markers,
                      polylines: _polylines,
                      myLocationEnabled: true,
                    ),
            ),
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  ElevatedButton(
                    onPressed: () async {
                      await _handleStartStop(true);
                    },
                    child: const Text('Start'),
                  ),
                  ElevatedButton(
                    onPressed: () async {
                      await _handleStartStop(false);
                    },
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                    ),
                    child: const Text('Stop'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  void dispose() {
    _locationService.onLocationUpdate = null;
    _breakTimer?.cancel();
    super.dispose();
  }
}
