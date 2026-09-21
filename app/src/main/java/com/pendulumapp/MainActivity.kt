package com.pendulumapp

import android.content.Intent
import android.content.res.AssetFileDescriptor
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
import kotlin.math.abs
import kotlin.math.min

class MainActivity : AppCompatActivity(), TextureView.SurfaceTextureListener {

    companion object {
        private const val BUNDLED_VIDEO_ASSET = "dancer.mp4"
        private const val BUNDLED_ANGLES_ASSET = "dancer_angles.json"
    }

    private lateinit var binding: ActivityMainBinding
    private var currentState = DetectionState.IDLE

    // The installation always has a bundled, pre-analyzed video + angle track (see
    // python/export_angle_track.py). The SAF picker below is a debug-only escape hatch for
    // visually smoke-testing an arbitrary video; a dev-picked video has no matching angle
    // track, so it plays at a fixed 1x with no pendulum tracking -- real closed-loop testing
    // always uses the bundled asset. See python/pendulum_sim_process.md for why the video
    // analysis itself stays offline/PC-side rather than running live on-device.
    private var angleTimeline: AngleTimeline? = null
    private var usingBundledVideo = true
    private var devVideoUri: Uri? = null

    private var mediaPlayer: MediaPlayer? = null
    private var surface: Surface? = null
    private var isPlayerPrepared = false
    // Start() may be pressed before prepareAsync() finishes; MediaPlayer.start() throws if
    // called before prepared, so a pending start is deferred to onPreparedListener instead.
    private var pendingAutoStart = false

    private var tiltSensor: PendulumTiltSensor? = null
    private var speedController: PendulumSpeedController? = null
    private var lastAppliedRate = 1.0f

    private val handler = Handler(Looper.getMainLooper())
    private var controlTickRunnable: Runnable? = null

    private val videoPickerLauncher = registerForActivityResult(
        ActivityResultContracts.OpenDocument()
    ) { uri: Uri? ->
        uri?.let {
            contentResolver.takePersistableUriPermission(
                it,
                Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
            devVideoUri = it
            usingBundledVideo = false
            setupMediaPlayerFromUri(it)
            Toast.makeText(this, R.string.video_selected, Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        binding.videoView.surfaceTextureListener = this
        binding.btnSelectVideo.visibility = if (BuildConfig.DEBUG) View.VISIBLE else View.GONE
        angleTimeline = loadBundledAngleTimeline()
        setupButtons()
        updateUI()
    }

    private fun loadBundledAngleTimeline(): AngleTimeline? = try {
        AngleTimeline.loadFromAsset(this, BUNDLED_ANGLES_ASSET)
    } catch (e: Exception) {
        null
    }

    override fun onSurfaceTextureAvailable(st: SurfaceTexture, w: Int, h: Int) {
        surface = Surface(st)
        when {
            mediaPlayer != null -> mediaPlayer?.setSurface(surface)
            usingBundledVideo -> setupMediaPlayerFromAsset(BUNDLED_VIDEO_ASSET)
            else -> devVideoUri?.let { setupMediaPlayerFromUri(it) }
        }
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
        binding.btnStart.setOnClickListener { startDetecting() }
        binding.btnPause.setOnClickListener { pauseDetecting() }
        binding.btnStop.setOnClickListener { stopDetecting() }
    }

    private fun onPlayerPrepared(mp: MediaPlayer) {
        isPlayerPrepared = true
        binding.videoView.post { applyVideoTransform(mp.videoWidth, mp.videoHeight) }
        if (pendingAutoStart && currentState == DetectionState.DETECTING) {
            pendingAutoStart = false
            mp.start()
        }
    }

    private fun setupMediaPlayerFromAsset(assetName: String) {
        isPlayerPrepared = false
        mediaPlayer?.release()
        val afd: AssetFileDescriptor = assets.openFd(assetName)
        mediaPlayer = MediaPlayer().apply {
            setDataSource(afd.fileDescriptor, afd.startOffset, afd.length)
            afd.close()
            surface?.let { setSurface(it) }
            setOnPreparedListener { mp -> onPlayerPrepared(mp) }
            setOnCompletionListener { mp ->
                speedController?.reset()
                mp.seekTo(0)
                mp.start()
            }
            setOnErrorListener { _, _, _ ->
                setupMediaPlayerFromAsset(BUNDLED_VIDEO_ASSET)
                true
            }
            prepareAsync()
        }
    }

    private fun setupMediaPlayerFromUri(uri: Uri) {
        isPlayerPrepared = false
        mediaPlayer?.release()
        mediaPlayer = MediaPlayer().apply {
            setDataSource(this@MainActivity, uri)
            surface?.let { setSurface(it) }
            setOnPreparedListener { mp -> onPlayerPrepared(mp) }
            setOnCompletionListener { mp ->
                mp.seekTo(0)
                mp.start()
            }
            setOnErrorListener { _, _, _ ->
                devVideoUri?.let { setupMediaPlayerFromUri(it) }
                true
            }
            prepareAsync()
        }
    }

    private fun startDetecting() {
        if (mediaPlayer == null) {
            Toast.makeText(this, R.string.select_video_first, Toast.LENGTH_SHORT).show()
            return
        }

        val fresh = currentState == DetectionState.IDLE
        if (tiltSensor == null) tiltSensor = PendulumTiltSensor(this)

        currentState = DetectionState.DETECTING
        updateUI()

        if (fresh) {
            lastAppliedRate = 1.0f
            val timeline = angleTimeline
            val sensor = tiltSensor!!
            speedController = if (timeline != null) {
                PendulumSpeedController(
                    timeline = timeline,
                    getLiveAngleDeg = { sensor.angleDeg },
                    getLiveAngularVelocityDegPerSec = { sensor.angularVelocityDegPerSec },
                    hasLiveAngle = { sensor.hasAngleReading },
                    getVideoPositionMs = { mediaPlayer?.currentPosition ?: 0 },
                    applySpeed = ::applySpeed,
                    onTick = ::onControlTick
                )
            } else {
                null
            }
            speedController?.reset()

            if (timeline == null) {
                binding.debugReadout.visibility = if (BuildConfig.DEBUG) View.VISIBLE else View.INVISIBLE
                binding.debugReadout.text = getString(R.string.dev_video_no_tracking)
            }

            if (isPlayerPrepared) {
                mediaPlayer?.seekTo(0)
            }
        }

        if (isPlayerPrepared) {
            mediaPlayer?.start()
        } else {
            pendingAutoStart = true
        }

        tiltSensor?.start()
        if (angleTimeline != null) startControlLoop()
    }

    private fun pauseDetecting() {
        pendingAutoStart = false
        stopControlLoop()
        tiltSensor?.stop()
        mediaPlayer?.pause()
        currentState = DetectionState.PAUSED
        updateUI()
    }

    private fun stopDetecting() {
        pendingAutoStart = false
        stopControlLoop()
        tiltSensor?.stop()
        tiltSensor = null
        speedController = null
        binding.debugReadout.visibility = View.INVISIBLE

        if (mediaPlayer?.isPlaying == true) mediaPlayer?.stop()
        if (usingBundledVideo) {
            setupMediaPlayerFromAsset(BUNDLED_VIDEO_ASSET)
        } else {
            devVideoUri?.let { setupMediaPlayerFromUri(it) }
        }

        currentState = DetectionState.IDLE
        updateUI()
    }

    private fun startControlLoop() {
        stopControlLoop()
        val r = object : Runnable {
            override fun run() {
                speedController?.tick()
                handler.postDelayed(this, PendulumTuning.TICK_INTERVAL_MS)
            }
        }
        controlTickRunnable = r
        handler.post(r)
    }

    private fun stopControlLoop() {
        controlTickRunnable?.let { handler.removeCallbacks(it) }
        controlTickRunnable = null
    }

    /** [PendulumSpeedController]'s applySpeed callback -- pushes the controller's chosen
     * playback rate to the real player, throttled so near-zero deltas don't cause audible
     * AudioTrack reconfiguration glitches (the controller's internal rate still updates
     * every tick regardless of whether this actually reaches the player). */
    private fun applySpeed(rate: Float) {
        val mp = mediaPlayer ?: return
        if (!isPlayerPrepared) return
        if (abs(rate - lastAppliedRate) < PendulumTuning.SPEED_APPLY_EPSILON) return
        try {
            mp.playbackParams = mp.playbackParams.setSpeed(rate).setPitch(1.0f)
            lastAppliedRate = rate
        } catch (e: IllegalStateException) {
            // Player mid-release/re-prepare (e.g. error recovery) -- skip, next tick retries.
        }
    }

    private fun onControlTick(info: PendulumSpeedController.TickInfo) {
        if (!BuildConfig.DEBUG) return
        binding.debugReadout.visibility = View.VISIBLE
        val errText = info.error?.let { String.format("%+.1f", it) } ?: "--"
        binding.debugReadout.text = String.format(
            "angle: %+.1f°  rate: %.2fx  err: %s°",
            info.liveAngleDeg, info.rate, errText
        )
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
        if (currentState == DetectionState.DETECTING) {
            stopControlLoop()
            tiltSensor?.stop()
        }
    }

    override fun onResume() {
        super.onResume()
        if (currentState == DetectionState.DETECTING) {
            tiltSensor?.start()
            if (angleTimeline != null) startControlLoop()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stopControlLoop()
        tiltSensor?.stop()
        tiltSensor = null
        speedController = null
        mediaPlayer?.release()
        mediaPlayer = null
        surface?.release()
        surface = null
    }
}
