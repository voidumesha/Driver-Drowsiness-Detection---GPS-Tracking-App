import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

class AdminScreen extends StatelessWidget {
  const AdminScreen({super.key});

  Future<String> _getAddress(Map<String, dynamic> lastLocation) async {
    try {
      final String apiKey = 'AIzaSyDrQkjLbhOQRTmYTGmti785_MPrJFAj99w';
      final String url =
          'https://maps.googleapis.com/maps/api/geocode/json?latlng=${lastLocation['latitude']},${lastLocation['longitude']}&key=$apiKey';

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
        title: const Text('Journey History'),
      ),
      body: StreamBuilder<QuerySnapshot>(
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
              final data = doc.data() as Map<String, dynamic>;
              final lastLocation =
                  data['lastLocation'] as Map<String, dynamic>?;
              final startTime = (data['startTime'] as Timestamp).toDate();
              final endTime = data['endTime'] != null
                  ? (data['endTime'] as Timestamp).toDate()
                  : null;

              return FutureBuilder<String>(
                future: lastLocation != null
                    ? _getAddress(lastLocation)
                    : Future.value('No location data'),
                builder: (context, addressSnapshot) {
                  return Card(
                    margin: const EdgeInsets.all(8.0),
                    child: Padding(
                      padding: const EdgeInsets.all(12.0),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'Journey ${index + 1}',
                            style: Theme.of(context).textTheme.titleLarge,
                          ),
                          const SizedBox(height: 8),
                          Text(
                              'Started: ${startTime.toString().split('.')[0]}'),
                          if (endTime != null)
                            Text('Ended: ${endTime.toString().split('.')[0]}'),
                          Text(
                              'Status: ${data['isActive'] ? 'Active' : 'Completed'}'),
                          const SizedBox(height: 4),
                          Text(
                              'Location: ${addressSnapshot.data ?? 'Loading...'}'),
                        ],
                      ),
                    ),
                  );
                },
              );
            },
          );
        },
      ),
    );
  }
}
