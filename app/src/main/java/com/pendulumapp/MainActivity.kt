package com.pendulumapp

import android.content.Intent
import android.graphics.Matrix
import android.graphics.SurfaceTexture
import android.media.MediaPlayer
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Surface
import android.view.TextureView
import android.view.View
import android.view.WindowManager
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.pendulumapp.databinding.ActivityMainBinding
import kotlin.math.min

class MainActivity : AppCompatActivity(), TextureView.SurfaceTextureListener {

    private lateinit var binding: ActivityMainBinding
    private var motionDetector: MotionDetector? = null
    private var currentState = DetectionState.IDLE
    private var videoUri: Uri? = null
    private var mediaPlayer: MediaPlayer? = null
    private var surface: Surface? = null
    private var isPlayerPrepared = false
    private val handler = Handler(Looper.getMainLooper())
    private var hideIndicatorRunnable: Runnable? = null

    private val videoPickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        uri?.let {
            contentResolver.takePersistableUriPermission(
                it,
                Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
            videoUri = it
            setupMediaPlayer(it)
            Toast.makeText(this, R.string.video_selected, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        binding.videoView.surfaceTextureListener = this
        setupButtons()
        updateUI()
    }

    override fun onSurfaceTextureAvailable(st: SurfaceTexture, w: Int, h: Int) {
        surface = Surface(st)
        // If a player already exists but has no surface (picked video before surface was ready), attach it now
        mediaPlayer?.setSurface(surface) ?: videoUri?.let { setupMediaPlayer(it) }
    }

    override fun onSurfaceTextureSizeChanged(st: SurfaceTexture, w: Int, h: Int) {}
    override fun onSurfaceTextureUpdated(st: SurfaceTexture) {}
    override fun onSurfaceTextureDestroyed(st: SurfaceTexture): Boolean {
        surface?.release()
        surface = null
        return true
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
        binding.btnPause.setOnClickListener { pauseDetecting() }
        binding.btnStop.setOnClickListener { stopDetecting() }
    }

    private fun setupMediaPlayer(uri: Uri) {
        isPlayerPrepared = false
        mediaPlayer?.release()
        mediaPlayer = MediaPlayer().apply {
            setDataSource(this@MainActivity, uri)
            surface?.let { setSurface(it) }
            setOnPreparedListener { mp ->
                isPlayerPrepared = true
                binding.videoView.post { applyVideoTransform(mp.videoWidth, mp.videoHeight) }
            }
            setOnCompletionListener { mp ->
                // Drive looping manually — more reliable than isLooping across Android versions
                mp.seekTo(0)
                mp.start()
            }
            setOnErrorListener { _, _, _ ->
                // On error, recreate the player so playback can resume
                videoUri?.let { setupMediaPlayer(it) }
                true
            }
            prepareAsync()
        }
    }

    private fun startDetecting() {
        if (motionDetector == null) {
            motionDetector = MotionDetector(this) {
                runOnUiThread { onMotionDetected() }
            }
        }
        currentState = DetectionState.DETECTING
        updateUI()

        Handler(Looper.getMainLooper()).postDelayed({
            if (currentState == DetectionState.DETECTING) {
                motionDetector?.startListening()
            }
        }, 1000)
    }

    private fun pauseDetecting() {
        motionDetector?.stopListening()
        mediaPlayer?.pause()
        currentState = DetectionState.PAUSED
        updateUI()
    }

    private fun stopDetecting() {
        motionDetector?.stopListening()
        motionDetector = null
        if (mediaPlayer?.isPlaying == true) mediaPlayer?.stop()
        videoUri?.let { setupMediaPlayer(it) }
        currentState = DetectionState.IDLE
        updateUI()
    }

    private fun onMotionDetected() {
        if (currentState == DetectionState.DETECTING && isPlayerPrepared) {
            mediaPlayer?.let { if (!it.isPlaying) it.start() }
        }
        showMotionIndicator()
    }

    private fun showMotionIndicator() {
        binding.motionIndicator.visibility = View.VISIBLE
        hideIndicatorRunnable?.let { handler.removeCallbacks(it) }
        hideIndicatorRunnable = Runnable {
            binding.motionIndicator.visibility = View.INVISIBLE
        }
        handler.postDelayed(hideIndicatorRunnable!!, 400)
    }

    private fun applyVideoTransform(videoWidth: Int, videoHeight: Int) {
        val tw = binding.videoView.width.toFloat()
        val th = binding.videoView.height.toFloat()
        if (tw == 0f || th == 0f || videoWidth == 0 || videoHeight == 0) return

        val vw = videoWidth.toFloat()
        val vh = videoHeight.toFloat()
        val cx = tw / 2f
        val cy = th / 2f

        val matrix = Matrix()
        // Undo MediaPlayer's stretch so the content represents the true video dimensions
        matrix.postScale(vw / tw, vh / th, cx, cy)
        // Rotate 90° clockwise
        matrix.postRotate(90f, cx, cy)
        // Scale rotated content (now vh×vw) to fit within the view (tw×th), preserving aspect ratio
        val scale = min(tw / vh, th / vw)
        matrix.postScale(scale, scale, cx, cy)

        binding.videoView.setTransform(matrix)
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
        if (currentState == DetectionState.DETECTING) motionDetector?.stopListening()
    }

    override fun onResume() {
        super.onResume()
        if (currentState == DetectionState.DETECTING) motionDetector?.startListening()
    }

    override fun onDestroy() {
        super.onDestroy()
        hideIndicatorRunnable?.let { handler.removeCallbacks(it) }
        motionDetector?.stopListening()
        motionDetector = null
        mediaPlayer?.release()
        mediaPlayer = null
        surface?.release()
        surface = null
    }
}
