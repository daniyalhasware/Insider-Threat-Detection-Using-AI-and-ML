let prevNetworkData = {
    bytes_sent: 0,
    bytes_recv: 0,
    packets_sent: 0,
    packets_recv: 0
};

// Function to fetch logs and update all tables and graphs
function fetchLogs() {
    fetch(`/user_details/${userId}`)
        .then((response) => response.json())
        .then((data) => {
            // Update process logs
            if (data.logs) {
                const logs = JSON.parse(data.logs);
                updateLogsTable(logs);
            }

            // Update network traffic graph and details
            if (data.network_traffic) {
                const networkTraffic = JSON.parse(data.network_traffic);

                // Ensure numbers
                const bytesSent = Number(networkTraffic.bytes_sent) || 0;
                const bytesRecv = Number(networkTraffic.bytes_recv) || 0;
                const packetsSent = Number(networkTraffic.packets_sent) || 0;
                const packetsRecv = Number(networkTraffic.packets_recv) || 0;

                const timeNow = Date.now();

                // Calculate deltas
                const bytesSentDelta = bytesSent - prevNetworkData.bytes_sent;
                const bytesRecvDelta = bytesRecv - prevNetworkData.bytes_recv;
                const packetsSentDelta = packetsSent - prevNetworkData.packets_sent;
                const packetsRecvDelta = packetsRecv - prevNetworkData.packets_recv;

                // Update totals table
                document.getElementById("bytes-sent-total").textContent = bytesSent.toLocaleString();
                document.getElementById("bytes-recv-total").textContent = bytesRecv.toLocaleString();
                document.getElementById("packets-sent-total").textContent = packetsSent.toLocaleString();
                document.getElementById("packets-recv-total").textContent = packetsRecv.toLocaleString();

                // Update deltas table
                document.getElementById("bytes-sent-delta").textContent = bytesSentDelta.toLocaleString();
                document.getElementById("bytes-recv-delta").textContent = bytesRecvDelta.toLocaleString();
                document.getElementById("packets-sent-delta").textContent = packetsSentDelta.toLocaleString();
                document.getElementById("packets-recv-delta").textContent = packetsRecvDelta.toLocaleString();

                // Update chart
                networkGraph.data.labels.push(timeNow);
                networkGraph.data.datasets[0].data.push(bytesRecv);
                networkGraph.data.datasets[1].data.push(bytesSent);

                if (networkGraph.data.labels.length > 60) {
                    networkGraph.data.labels.shift();
                    networkGraph.data.datasets[0].data.shift();
                    networkGraph.data.datasets[1].data.shift();
                }
                networkGraph.update();

                // Save to localStorage
                localStorage.setItem(
                    `networkGraphData_${userId}`,
                    JSON.stringify({
                        labels: networkGraph.data.labels,
                        datasets: networkGraph.data.datasets,
                    })
                );

                // Save current values for next delta
                prevNetworkData = {
                    bytes_sent: bytesSent,
                    bytes_recv: bytesRecv,
                    packets_sent: packetsSent,
                    packets_recv: packetsRecv
                };
            }

            // Update web activity
            if (data.web_activity) {
                updateWebActivityTable(data.web_activity);
            }

            // Update network activity
            if (data.network_activity) {
                updateNetworkActivityTable(data.network_activity);
            }

            // Update locations
            if (data.locations) {
                updateLocationTable(JSON.parse(data.locations));
            }
        })
        .catch((err) => console.log("Error fetching logs:", err));
}

// Initialize everything when page loads
window.addEventListener("load", function () {
    // Initialize map with locations from template
    const locations = JSON.parse('{{ locations | tojson | safe }}');
    initMap(locations);
    
    loadFileAccess();
    
    // Set initial values from template
    const initialNetworkTraffic = JSON.parse('{{ network_traffic | tojson | safe }}');
    if (initialNetworkTraffic) {
        document.getElementById("bytes-sent-total").textContent = (initialNetworkTraffic.bytes_sent || 0).toLocaleString();
        document.getElementById("bytes-recv-total").textContent = (initialNetworkTraffic.bytes_recv || 0).toLocaleString();
        document.getElementById("packets-sent-total").textContent = (initialNetworkTraffic.packets_sent || 0).toLocaleString();
        document.getElementById("packets-recv-total").textContent = (initialNetworkTraffic.packets_recv || 0).toLocaleString();
        
        // Set initial values for delta calculation
        prevNetworkData = {
            bytes_sent: initialNetworkTraffic.bytes_sent || 0,
            bytes_recv: initialNetworkTraffic.bytes_recv || 0,
            packets_sent: initialNetworkTraffic.packets_sent || 0,
            packets_recv: initialNetworkTraffic.packets_recv || 0
        };
    }
    
    fetchLogs();

    // Poll every 5 seconds
    setInterval(fetchLogs, 5000);
});