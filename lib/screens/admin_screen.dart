import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:url_launcher/url_launcher.dart';

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
              final data = snapshot.data!.docs[index].data();
              final startTime = (data['startTime'] as Timestamp).toDate();
              final endTime = data['endTime'] != null
                  ? (data['endTime'] as Timestamp).toDate()
                  : null;

              return ExpansionTile(
                title: Text('Journey ${index + 1}'),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Date: ${startTime.toString().split('.')[0]}'),
                    StreamBuilder<DocumentSnapshot>(
                      stream: FirebaseFirestore.instance
                          .collection('breaking')
                          .doc('status')
                          .snapshots(),
                      builder: (context, breakSnapshot) {
                        int breakCount = 0;
                        if (breakSnapshot.hasData &&
                            breakSnapshot.data!.exists) {
                          breakCount = (breakSnapshot.data!.data()
                                  as Map<String, dynamic>)['breakCount'] ??
                              0;
                        }
                        return Text('Total Breaks: $breakCount');
                      },
                    ),
                    if (data['distance'] != null)
                      Text(
                          'Distance: ${(double.parse(data['distance'].toString())).toStringAsFixed(2)} km'),
                  ],
                ),
                children: [
                  // Start Location with address
                  if (data['startLocation'] != null)
                    FutureBuilder<String>(
                      future: _getAddress(
                        data['startLocation']['latitude'],
                        data['startLocation']['longitude'],
                      ),
                      builder: (context, startSnapshot) {
                        return ListTile(
                          title: const Text('Start Location:'),
                          subtitle: Text(startSnapshot.data ?? 'Loading...'),
                        );
                      },
                    ),

                  // Destination with address
                  if (data['destination'] != null)
                    FutureBuilder<String>(
                      future: _getAddress(
                        data['destination']['latitude'],
                        data['destination']['longitude'],
                      ),
                      builder: (context, destSnapshot) {
                        return ListTile(
                          title: const Text('Destination:'),
                          subtitle: Text(destSnapshot.data ?? 'Loading...'),
                        );
                      },
                    ),

                  // Break History
                  if (data['breaks'] != null &&
                      (data['breaks'] as List).isNotEmpty)
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Padding(
                          padding: EdgeInsets.all(8.0),
                          child: Text(
                            'Break History',
                            style: TextStyle(
                                fontSize: 18, fontWeight: FontWeight.bold),
                          ),
                        ),
                        ...List.generate(
                          (data['breaks'] as List).length,
                          (i) => FutureBuilder<String>(
                            future: _getAddress(
                              data['breaks'][i]['location']['latitude'],
                              data['breaks'][i]['location']['longitude'],
                            ),
                            builder: (context, breakSnapshot) {
                              final breakTime =
                                  (data['breaks'][i]['time'] as Timestamp)
                                      .toDate()
                                      .toString()
                                      .split('.')[0];
                              return Card(
                                margin: const EdgeInsets.symmetric(
                                    horizontal: 8, vertical: 4),
                                child: ListTile(
                                  leading: CircleAvatar(
                                    child: Text('${i + 1}'),
                                  ),
                                  title: Text('Break #${i + 1}'),
                                  subtitle: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text('Time: $breakTime'),
                                      Text(
                                          'Location: ${breakSnapshot.data ?? 'Loading...'}'),
                                      if (data['breaks'][i]['duration'] != null)
                                        Text(
                                            'Duration: ${data['breaks'][i]['duration']} minutes'),
                                      TextButton(
                                        onPressed: () async {
                                          final lat = data['breaks'][i]
                                              ['location']['latitude'];
                                          final lng = data['breaks'][i]
                                              ['location']['longitude'];
                                          final url =
                                              'https://www.google.com/maps/search/?api=1&query=$lat,$lng';
                                          if (await canLaunchUrl(
                                              Uri.parse(url))) {
                                            await launchUrl(Uri.parse(url));
                                          }
                                        },
                                        child: const Text('View on Map'),
                                      ),
                                    ],
                                  ),
                                ),
                              );
                            },
                          ),
                        ),
                      ],
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
