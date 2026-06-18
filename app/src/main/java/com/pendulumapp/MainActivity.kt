package com.pendulumapp

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.pendulumapp.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private var motionDetector: MotionDetector? = null
    private var currentState = DetectionState.IDLE
    private var videoUri: Uri? = null
    private var videoStopped = false

    private val videoPickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        uri?.let {
            contentResolver.takePersistableUriPermission(
                it,
                Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
            videoUri = it
            videoStopped = false
            setupVideoView(it)
            Toast.makeText(this, R.string.video_selected, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        setupButtons()
        updateUI()
    }

    private fun setupButtons() {
        binding.btnSelectVideo.setOnClickListener {
            videoPickerLauncher.launch(arrayOf("video/*"))
        }

        binding.btnStart.setOnClickListener {
            if (videoUri == null) {
                Toast.makeText(this, R.string.select_video_first, Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            startDetecting()
        }

        binding.btnPause.setOnClickListener {
            pauseDetecting()
        }

        binding.btnStop.setOnClickListener {
            stopDetecting()
        }
    }

    private fun startDetecting() {
        if (videoStopped && videoUri != null) {
            setupVideoView(videoUri!!)
            videoStopped = false
        }

        if (motionDetector == null) {
            motionDetector = MotionDetector(this) {
                runOnUiThread { onMotionDetected() }
            }
        }
        motionDetector?.startListening()
        currentState = DetectionState.DETECTING
        updateUI()
    }

    private fun pauseDetecting() {
        motionDetector?.stopListening()
        binding.videoView.pause()
        currentState = DetectionState.PAUSED
        updateUI()
    }

    private fun stopDetecting() {
        motionDetector?.stopListening()
        motionDetector = null
        binding.videoView.stopPlayback()
        videoStopped = true
        currentState = DetectionState.IDLE
        updateUI()
    }

    private fun onMotionDetected() {
        if (currentState == DetectionState.DETECTING && videoUri != null) {
            binding.videoView.seekTo(0)
            binding.videoView.start()
        }
    }

    private fun setupVideoView(uri: Uri) {
        binding.videoView.setVideoURI(uri)
        binding.videoView.setOnPreparedListener { mp ->
            mp.isLooping = true
        }
        binding.videoView.setOnErrorListener { _, _, _ ->
            Toast.makeText(this, "Video playback error", Toast.LENGTH_SHORT).show()
            true
        }
    }

    private fun updateUI() {
        when (currentState) {
            DetectionState.IDLE -> {
                binding.btnStart.isEnabled = true
                binding.btnPause.isEnabled = false
                binding.btnStop.isEnabled = false
                binding.btnSelectVideo.isEnabled = true
                binding.statusText.setText(R.string.status_idle)
            }
            DetectionState.DETECTING -> {
                binding.btnStart.isEnabled = false
                binding.btnPause.isEnabled = true
                binding.btnStop.isEnabled = true
                binding.btnSelectVideo.isEnabled = false
                binding.statusText.setText(R.string.status_detecting)
            }
            DetectionState.PAUSED -> {
                binding.btnStart.isEnabled = true
                binding.btnPause.isEnabled = false
                binding.btnStop.isEnabled = true
                binding.btnSelectVideo.isEnabled = false
                binding.statusText.setText(R.string.status_paused)
            }
        }
    }

    override fun onPause() {
        super.onPause()
        if (currentState == DetectionState.DETECTING) {
            motionDetector?.stopListening()
        }
    }

    override fun onResume() {
        super.onResume()
        if (currentState == DetectionState.DETECTING) {
            motionDetector?.startListening()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        motionDetector?.stopListening()
        motionDetector = null
    }
}
