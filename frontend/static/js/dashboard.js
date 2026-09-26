document.addEventListener('DOMContentLoaded', function() {
    // Audio elements
    const anomalySound = document.getElementById('anomaly-sound');
    const usbSound = document.getElementById('usb-sound');
    
    // Initialize audio
    function initAudio() {
        anomalySound.volume = 0.3;
        usbSound.volume = 0.3;
        
        // A more reliable way to unlock audio
        const unlockAudio = () => {
            document.removeEventListener('click', unlockAudio);
            const promises = [anomalySound.play(), usbSound.play()];
            Promise.all(promises).then(() => {
                anomalySound.pause();
                usbSound.pause();
                anomalySound.currentTime = 0;
                usbSound.currentTime = 0;
            }).catch(e => console.log("Audio unlock error:", e));
        };
        document.addEventListener('click', unlockAudio);
    }
    
    // Play anomaly sound
    function playAnomalySound() {
        console.log("Attempting to play anomaly sound.");
        if (anomalySound.paused) {
            anomalySound.currentTime = 0;
            anomalySound.play().catch(e => console.error("Anomaly sound play error:", e));
        } else {
            console.log("Anomaly sound is already playing.");
        }
    }
    
    // Play USB sound
    function playUsbSound() {
        console.log("Attempting to play USB sound.");
        if (usbSound.paused) {
            usbSound.currentTime = 0;
            usbSound.play().catch(e => console.error("USB sound play error:", e));
        } else {
            console.log("USB sound is already playing.");
        }
    }
    
    // Initialize
    initAudio();
    
    // Socket.IO connection
    const socket = io();
    
    // Track online users and anomaly count
    const onlineUsers = new Set();
    let anomalyCount = 0;
    
    // Update user counts display
    function updateUserCounts() {
        const totalUsers = document.querySelectorAll('.user-tile').length;
        const onlineCount = onlineUsers.size;
        const offlineCount = totalUsers - onlineCount;
        
        document.getElementById('total-count').textContent = totalUsers;
        document.getElementById('online-count').textContent = onlineCount;
        document.getElementById('offline-count').textContent = offlineCount;
        document.getElementById('anomaly-count').textContent = anomalyCount;
    }
    
    // Handle new anomaly alert
    socket.on('insider_threat_alert', function(data) {
        anomalyCount++;
        updateUserCounts();
        playAnomalySound();
        
        const container = document.getElementById('alerts-container');
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert';
        alertDiv.innerHTML = `
            <strong>${new Date().toLocaleTimeString()} - Anomaly Detected!</strong>
            <div>User: ${data.user_id}</div>
            <div>Score: ${data.score.toFixed(2)}</div>
            <button class="btn btn-sm btn-outline-info mt-2" 
                    onclick="showAnomalyDetails('${data.user_id}', ${JSON.stringify(data).replace(/"/g, '&quot;')})">
                View Details
            </button>
        `;
        container.prepend(alertDiv);
        
        // Highlight user tile
        const userTile = document.getElementById(`user-${data.user_id}`);
        if (userTile) {
            userTile.classList.add('anomaly-detected');
            setTimeout(() => {
                userTile.classList.remove('anomaly-detected');
            }, 10000);
        }
    });
    
    // Handle USB alert
    socket.on('usb_alert', function(data) {
        playUsbSound();
        
        const container = document.getElementById('usb-alerts-container');
        const alertDiv = document.createElement('div');
        alertDiv.className = 'usb-alert';
        alertDiv.textContent = data.message;
        container.appendChild(alertDiv);
        container.scrollTop = container.scrollHeight;
    });
    
    // Other socket handlers (keep your existing ones)
    socket.on('connect', () => console.log('Connected to server'));
    
    // Make functions available globally
    window.playAnomalySound = playAnomalySound;
    window.playUsbSound = playUsbSound;
    window.showAnomalyDetails = showAnomalyDetails;
    window.updateUserCounts = updateUserCounts;
});

// Global function to show anomaly details
function showAnomalyDetails(userId, data) {
    const content = document.getElementById('anomaly-details-content');
    content.innerHTML = `
        <div class="mb-3"><strong>User ID:</strong> ${userId}</div>
        <div class="mb-3"><strong>Alert Message:</strong> ${data.message}</div>
        <div class="mb-3"><strong>Anomaly Score:</strong> ${data.score.toFixed(2)}</div>
        <div class="mb-3"><strong>Reasons:</strong></div>
        <ul class="mb-3">${data.reasons.map(r => `<li>${r}</li>`).join('')}</ul>
        <div class="mb-3"><strong>Metrics:</strong></div>
        <table class="table table-sm">
            <thead>
                <tr>
                    <th>Metric</th>
                    <th>Value</th>
                </tr>
            </thead>
            <tbody>
                <tr><td>CPU Usage</td><td>${data.metrics.cpu.toFixed(1)}%</td></tr>
                <tr><td>Memory Usage</td><td>${data.metrics.memory.toFixed(1)}%</td></tr>
                <tr><td>Network Traffic</td><td>${(data.metrics.network / 1024 / 1024).toFixed(2)} MB</td></tr>
                <tr><td>USB Connected</td><td>${data.metrics.usb ? 'Yes' : 'No'}</td></tr>
            </tbody>
        </table>
    `;
    
    const modal = new bootstrap.Modal(document.getElementById('anomalyModal'));
    modal.show();
}