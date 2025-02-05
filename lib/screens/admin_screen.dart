import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

class AdminScreen extends StatelessWidget {
  const AdminScreen({super.key});

  Future<String> _getAddress(double lat, double lng) async {
    try {
      final String apiKey = 'AIzaSyDrQkjLbhOQRTmYTGmti785_MPrJFAj99w';
      final String url =
          'https://maps.googleapis.com/maps/api/geocode/json?latlng=$lat,$lng&key=$apiKey';

      final response = await http.get(Uri.parse(url));
      final data = json.decode(response.body);

      if (data['status'] == 'OK') {
        return data['results'][0]['formatted_address'];
      }
      return 'Address not found';
    } catch (e) {
      return 'Error getting address';
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Journey Reports'),
      ),
      body: StreamBuilder<QuerySnapshot<Map<String, dynamic>>>(
        stream: FirebaseFirestore.instance
            .collection('journeys')
            .orderBy('startTime', descending: true)
            .snapshots(),
        builder: (context, snapshot) {
          if (!snapshot.hasData) {
            return const Center(child: CircularProgressIndicator());
          }

          return ListView.builder(
            itemCount: snapshot.data!.docs.length,
            itemBuilder: (context, index) {
              final doc = snapshot.data!.docs[index];
              final data = doc.data();

              return ExpansionTile(
                title: Text('Journey ${index + 1}'),
                subtitle: Text(
                    'Status: ${data['isActive'] ? 'Active' : 'Completed'}\n'
                    'Started: ${(data['startTime'] as Timestamp).toDate().toString().split('.')[0]}'),
                children: [
                  FutureBuilder<String>(
                    future: _getAddress(
                      data['startLocation']['latitude'],
                      data['startLocation']['longitude'],
                    ),
                    builder: (context, startSnapshot) {
                      return ListTile(
                        title: Text('Start Location:'),
                        subtitle: Text(startSnapshot.data ?? 'Loading...'),
                      );
                    },
                  ),
                  if (data['destination'] != null)
                    FutureBuilder<String>(
                      future: _getAddress(
                        data['destination']['latitude'],
                        data['destination']['longitude'],
                      ),
                      builder: (context, destSnapshot) {
                        return ListTile(
                          title: Text('Destination:'),
                          subtitle: Text(destSnapshot.data ?? 'Loading...'),
                        );
                      },
                    ),
                  if (data['breaks'] != null)
                    ...List.generate(
                      (data['breaks'] as List).length,
                      (i) => FutureBuilder<String>(
                        future: _getAddress(
                          data['breaks'][i]['location']['latitude'],
                          data['breaks'][i]['location']['longitude'],
                        ),
                        builder: (context, breakSnapshot) {
                          return ListTile(
                            title: Text('Break ${i + 1}:'),
                            subtitle: Text(
                                'Time: ${(data['breaks'][i]['time'] as Timestamp).toDate().toString().split('.')[0]}\n'
                                'Location: ${breakSnapshot.data ?? 'Loading...'}'),
                          );
                        },
                      ),
                    ),
                  if (data['alertLocations'] != null)
                    ...List.generate(
                      (data['alertLocations'] as List).length,
                      (i) => FutureBuilder<String>(
                        future: _getAddress(
                          data['alertLocations'][i]['latitude'],
                          data['alertLocations'][i]['longitude'],
                        ),
                        builder: (context, alertSnapshot) {
                          return ListTile(
                            leading: Icon(Icons.warning, color: Colors.red),
                            title: Text('Alert Location ${i + 1}:'),
                            subtitle: Text(alertSnapshot.data ?? 'Loading...'),
                          );
                        },
                      ),
                    ),
                ],
              );
            },
          );
        },
      ),
    );
  }
}
