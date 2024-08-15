import traceback
from enum import Enum
from gc import collect
from math import degrees, isclose

from android.permissions import Permission, request_permissions
from jnius import PythonJavaClass, autoclass, cast, java_method
from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.event import EventDispatcher
from kivy.graphics import Fbo, Rectangle
from kivy.graphics.texture import Texture
from kivy.lang import Builder
from kivy.logger import Logger
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             ObjectProperty, OptionProperty, StringProperty)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.widget import Widget

__all__ = ('Camera2Widget', 'Camera2Layout')

ArrayList = autoclass('java.util.ArrayList')
CameraCharacteristics = autoclass("android.hardware.camera2.CameraCharacteristics")
CameraDevice = autoclass("android.hardware.camera2.CameraDevice")
CaptureRequest = autoclass("android.hardware.camera2.CaptureRequest")
Context = autoclass("android.content.Context")
GL_TEXTURE_EXTERNAL_OES = autoclass('android.opengl.GLES11Ext').GL_TEXTURE_EXTERNAL_OES
Handler = autoclass("android.os.Handler")
HandlerThread = autoclass('android.os.HandlerThread')
MyCaptureSessionCallback = autoclass("org.kivy.android.MyCaptureSessionCallback")
MyStateCallback = autoclass("org.kivy.android.MyStateCallback")
PythonActivity = autoclass("org.kivy.android.PythonActivity")
Sensor = autoclass('android.hardware.Sensor')
SensorEventListener = autoclass('android.hardware.SensorEventListener')
SensorManager = autoclass('android.hardware.SensorManager')
Surface = autoclass('android.view.Surface')
SurfaceTexture = autoclass('android.graphics.SurfaceTexture')

Builder.load_string('''
<Camera2Widget>:
    id: camera
    canvas:
        PushMatrix
        Rotate:
            angle: -90
            origin: self.center
        Color:
            rgba: 1, 1, 1, 1
        Rectangle:
            pos: self._rect_pos
            size: self._rect_size
            texture: root.texture
        PopMatrix

<Camera2Layout>:
    Camera2Widget:
        id: camera
        camera_angle: root.camera_angle
        fps: root.fps
    Image:
        source: 'camera-large.png'
        size_hint: None, None
        size: self.texture_size
        pos_hint: {'center_x': .5, 'center_y': .5}
        opacity: .3
        canvas.before:
            PushMatrix
            Rotate:
                angle: camera.rotation
                origin: self.center
        canvas.after:
            PopMatrix
    Widget:
        canvas.before:
            Color:
                rgba: 1, 1, 1, .3
            SmoothLine:
                width: dp(1)
                rounded_rectangle: self.x + dp(20), self.y  + dp(20), \
                    self.width - dp(40), self.height - dp(40), dp(2)
    CaptureButton:
        on_release: camera.shot()
        size_hint: None, None
        size: dp(80), dp(80)
        pos_hint: {'center_x': .5, 'center_y': .2}
        canvas.before:
            Color:
                rgba: 0, 0, 0, .3
            BoxShadow:
                pos: self.pos
                size: self.size
                offset: 0, 0
                spread_radius: -dp(10), -dp(10)
                border_radius: [dp(30), ] * 4
                blur_radius: 50
            Color:
                rgba: .7, 1, .7, 1 if self.state == 'down' else .8
            RoundedRectangle:
                size: self.size
                pos: self.pos
                radius: (dp(50), )
''')


class CaptureButton(ButtonBehavior, Widget):
    pass


class Runnable(PythonJavaClass):
    __javainterfaces__ = ['java/lang/Runnable']

    def __init__(self, func):
        super().__init__()
        self.func = func

    @java_method('()V')
    def run(self):
        try:
            self.func()
        except Exception:  # pylint: disable=broad-except
            traceback.print_exc()


class TiltDetector(PythonJavaClass):
    __javainterfaces__ = ['android/hardware/SensorEventListener']

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        context = PythonActivity.mActivity.getApplicationContext()
        self.SensorManager = cast('android.hardware.SensorManager',  # pylint: disable=invalid-name
                                  context.getSystemService(Context.SENSOR_SERVICE))
        self.sensor = self.SensorManager.getDefaultSensor(
            Sensor.TYPE_ACCELEROMETER)

        self.magnetometer = self.SensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
        self.SensorManager.registerListener(self, self.magnetometer,
                                            SensorManager.SENSOR_DELAY_NORMAL)
        self.mGeomagnetic = [0, 0, 0]  # pylint: disable=invalid-name
        self.mGravity = [0, 0, 0]  # pylint: disable=invalid-name
        self.angle = 90

    @java_method('(Landroid/hardware/SensorEvent;)V')
    def onSensorChanged(self, event):  # pylint: disable=invalid-name
        if event.sensor.getType() == Sensor.TYPE_ACCELEROMETER:
            self.mGravity = list(event.values)
        elif event.sensor.getType() == Sensor.TYPE_MAGNETIC_FIELD:
            self.mGeomagnetic = list(event.values)

        if self.mGravity is not None and self.mGeomagnetic is not None:
            rotationmatrix = [0] * 9
            success = SensorManager.getRotationMatrix(rotationmatrix, None, self.mGravity,
                                                      self.mGeomagnetic)
            if success:
                orientation = [0] * 3
                SensorManager.getOrientation(rotationmatrix, orientation)
                pitch = degrees(orientation[1])
                roll = degrees(orientation[2])
                angle = self.angle

                if 135 > abs(roll) > 45:
                    if roll < 0 and 30 > pitch > -30:
                        angle = -90  # Left
                    else:
                        if roll > 20 and 30 > pitch > -30:
                            angle = 90  # Right
                        else:
                            angle = 0  # Portrait
                    self.angle = angle

    def enable(self):
        self.SensorManager.registerListener(self, self.sensor,
                                            SensorManager.SENSOR_DELAY_NORMAL)
        self.SensorManager.registerListener(self, self.magnetometer,
                                            SensorManager.SENSOR_DELAY_NORMAL)
        Logger.debug('Enabled TiltDetector')

    def disable(self):
        self.SensorManager.unregisterListener(self, self.sensor)
        self.SensorManager.unregisterListener(self, self.magnetometer)
        Logger.debug('Disabled TiltDetector')

    @java_method('(Landroid/hardware/Sensor;I)V')
    def onAccuracyChanged(self, sensor, accuracy):  # pylint: disable=invalid-name
        pass

    def __del__(self):
        self.disable()
        self.SensorManager = None


def get_suitable_camera_size(resolutions):
    try:
        aspect_ratio_16_9 = [item for item in resolutions if isclose(item[0] / item[1], 16/9)]
        length = int(len(aspect_ratio_16_9) * 0.2)  # 20%
        return aspect_ratio_16_9[length:][0]  # 9, 8.. -20%
    except Exception:  # pylint: disable=broad-except
        return resolutions[0]


class LensFacing(Enum):
    """Values copied from CameraCharacteristics api doc, as pyjnius
    lookup doesn't work on some devices.
    """
    LENS_FACING_FRONT = 0
    LENS_FACING_BACK = 1
    LENS_FACING_EXTERNAL = 2


class ControlAfMode(Enum):
    CONTROL_AF_MODE_CONTINUOUS_PICTURE = 4


class ControlAeMode(Enum):
    CONTROL_AE_MODE_ON = 1


class PyCameraInterface(EventDispatcher):
    """
    Provides an API for querying details of the cameras available on Android.
    """
    camera_angle = NumericProperty()
    camera_ids: list = []
    cameras: list = ListProperty()
    fps = NumericProperty(60)
    java_camera_characteristics: dict = {}
    java_camera_manager = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        Logger.debug("Starting camera interface init")
        context = cast("android.content.Context", PythonActivity.mActivity)
        self.java_camera_manager = cast("android.hardware.camera2.CameraManager",
                                        context.getSystemService(Context.CAMERA_SERVICE))
        self.camera_ids = self.java_camera_manager.getCameraIdList()
        characteristics_dict = self.java_camera_characteristics
        camera_manager = self.java_camera_manager
        Logger.debug("Got basic java objects")

        for camera_id in self.camera_ids:
            Logger.debug("Getting data for camera %s", camera_id)
            characteristics_dict[camera_id] = camera_manager.getCameraCharacteristics(camera_id)
            Logger.debug("Got characteristics dict")
            self.cameras.append(PyCameraDevice(
                camera_angle=self.camera_angle,
                camera_id=camera_id,
                fps=self.fps,
                java_camera_characteristics=characteristics_dict[camera_id],
                java_camera_manager=camera_manager))
            Logger.debug("Finished interpreting camera %s", camera_id)

    def select_cameras(self, **conditions):
        outputs = []
        for camera in self.cameras:
            for key, value in conditions.items():
                if getattr(camera, key) != value:
                    break
            else:
                outputs.append(camera)

        return outputs


class PyCameraDevice(EventDispatcher):  # pylint: disable=too-many-instance-attributes
    __events__ = ('on_opened', 'on_closed', 'on_disconnected', 'on_error')
    camera_angle = NumericProperty()
    camera_id = StringProperty()
    fps = NumericProperty(60)
    preview_texture = ObjectProperty(None, allownone=True)
    preview_resolution = ListProperty()
    preview_fbo = ObjectProperty(None, allownone=True)
    java_preview_surface_texture = ObjectProperty(None, allownone=True)
    java_preview_surface = ObjectProperty(None, allownone=True)
    java_capture_request = ObjectProperty(None, allownone=True)
    java_surface_list = ObjectProperty(None, allownone=True)
    java_capture_session = ObjectProperty(None, allownone=True)
    connected = BooleanProperty(False)
    supported_resolutions = ListProperty()
    facing = OptionProperty("UNKNOWN", options=["UNKNOWN", "FRONT", "BACK", "EXTERNAL"])
    java_camera_characteristics = ObjectProperty()
    java_camera_manager = ObjectProperty()
    java_camera_device = ObjectProperty(None, allownone=True)
    java_stream_configuration_map = ObjectProperty()
    _open_callback = ObjectProperty(None, allownone=True)
    listener = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._java_state_callback_runnable = Runnable(self._java_state_callback)
        self._java_state_java_callback = MyStateCallback(self._java_state_callback_runnable)

        self._java_capture_session_callback_runnable = Runnable(self._java_capture_session_callback)
        self._java_capture_session_java_callback = MyCaptureSessionCallback(
            self._java_capture_session_callback_runnable)
        self._populate_camera_characteristics()

    def on_opened(self, instance):
        pass

    def on_closed(self, instance):
        pass

    def on_disconnected(self, instance):
        pass

    def on_error(self, instance, error):
        pass

    def close(self):
        Logger.info("Attempt to clean up resources")
        self._open_callback = None
        Clock.unschedule(self._update_preview)

        if self.handler_thread is not None:
            self.handler_thread.quit()
            self.handler_thread = None
            self.background_handler = None

        for attr_name in ['java_camera_device', 'java_capture_session',
                          'java_preview_surface', 'java_capture_request',
                          'java_surface_list', 'java_preview_surface_texture']:
            java_obj = getattr(self, attr_name, None)
            if java_obj is not None:
                try:
                    if hasattr(java_obj, 'close'):
                        java_obj.close()
                    elif hasattr(java_obj, 'clear'):
                        java_obj.clear()
                    elif hasattr(java_obj, 'release'):
                        java_obj.release()
                except AttributeError as err:
                    Logger.debug('Error shutting down %s: %s', attr_name, err)
                setattr(self, attr_name, None)

    def _populate_camera_characteristics(self):
        Logger.debug("Populating camera characteristics")
        self.java_stream_configuration_map = self.java_camera_characteristics.get(
            CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP)
        Logger.debug("Got stream configuration map")

        self.supported_resolutions = [
            (size.getWidth(), size.getHeight()) for size in
            self.java_stream_configuration_map.getOutputSizes(SurfaceTexture(0).getClass())]
        Logger.debug("Got supported resolutions")

        facing = self.java_camera_characteristics.get(
            CameraCharacteristics.LENS_FACING)
        Logger.debug("Got facing: %s", facing)

        if facing == LensFacing.LENS_FACING_BACK.value:
            self.facing = "BACK"
        elif facing == LensFacing.LENS_FACING_FRONT.value:
            self.facing = "FRONT"
        elif facing == LensFacing.LENS_FACING_EXTERNAL.value:
            self.facing = "EXTERNAL"
        else:
            raise ValueError(f"Camera id {self.camera_id} LENS_FACING is unknown value {facing}")

        Logger.debug("Finished initing camera %s", self.camera_id)

    def __str__(self):
        return f"<PyCameraDevice facing={self.facing}>"

    def __repr__(self):
        return str(self)

    def open(self, callback=None, frame_trigger=None):
        self.remote_frame_trigger = frame_trigger
        self._open_callback = callback
        self.handler_thread = HandlerThread("camera_background_thread")
        self.handler_thread.start()

        self.background_handler = Handler(self.handler_thread.getLooper())
        self.java_camera_manager.openCamera(self.camera_id,
                                            self._java_state_java_callback,
                                            self.background_handler)

    def _java_state_callback(self):
        action = self._java_state_java_callback.getCameraAction().toString()
        camera_device = self._java_state_java_callback.getCameraDevice()
        self.java_camera_device = camera_device
        Logger.debug("CALLBACK: camera event %s", action)

        if action in ('OPENED', 'DISCONNECTED', 'CLOSED', 'ERROR', 'UNKNOWN'):
            self.dispatch(f'on_{action.lower()}', self)
            self.connected = action == 'OPENED'
        else:
            raise ValueError(f"Received unknown camera action {action}")

        self._open_callback(self, action)

    def start_preview(self, resolution):
        if isinstance(resolution, list):
            resolution = tuple(resolution)

        if self.java_camera_device is None:
            raise ValueError("Camera device not yet opened, cannot create preview stream")

        if resolution not in self.supported_resolutions:
            raise ValueError(f"Tried to open preview with resolution {resolution}, "
                             f"not in supported resolutions {self.supported_resolutions}")

        Logger.info("Creating capture stream with resolution %s", resolution)

        self.preview_resolution = resolution
        self._prepare_preview_fbo(resolution)
        self.preview_texture = Texture(width=resolution[0], height=resolution[1],
                                       target=GL_TEXTURE_EXTERNAL_OES, colorfmt="rgba")
        Logger.debug("Texture id is %s", self.preview_texture.id)

        java_resolution_list = ArrayList()
        for item in resolution:
            java_resolution_list.add(item)

        self.java_preview_surface_texture = SurfaceTexture(int(self.preview_texture.id))
        self.java_preview_surface_texture.setDefaultBufferSize(*java_resolution_list)
        self.java_preview_surface = Surface(self.java_preview_surface_texture)
        self.java_capture_request = self.java_camera_device.createCaptureRequest(
                CameraDevice.TEMPLATE_PREVIEW)
        self.java_capture_request.addTarget(self.java_preview_surface)
        self.java_capture_request.set(
            CaptureRequest.CONTROL_AF_MODE, ControlAfMode.CONTROL_AF_MODE_CONTINUOUS_PICTURE.value)
        self.java_capture_request.set(
            CaptureRequest.CONTROL_AE_MODE, ControlAeMode.CONTROL_AE_MODE_ON.value)
        self.java_surface_list = ArrayList()
        self.java_surface_list.add(self.java_preview_surface)

        self.java_camera_device.createCaptureSession(self.java_surface_list,
                                                     self._java_capture_session_java_callback,
                                                     self.background_handler)

        return self.preview_fbo.texture

    def _prepare_preview_fbo(self, resolution):
        self.preview_fbo = Fbo(size=resolution)
        self.preview_fbo['resolution'] = [float(f) for f in resolution]
        self.preview_fbo['angle'] = float(self.camera_angle * (3.14159 / 180))
        self.preview_fbo.shader.fs = """
            #extension GL_OES_EGL_image_external : require
            #ifdef GL_ES
            precision highp float;
            #endif

            varying vec4 frag_color;
            varying vec2 tex_coord0;

            uniform samplerExternalOES texture1;
            uniform vec2 resolution;
            uniform float angle;

            void main() {
                float viewportAspectRatio = resolution.x / resolution.y;
                float textureWidth;
                float textureHeight;

                if (viewportAspectRatio > 1.0) {
                    textureWidth = resolution.x;
                    textureHeight = resolution.x / viewportAspectRatio;
                } else {
                    textureWidth = resolution.y * viewportAspectRatio;
                    textureHeight = resolution.y;
                }

                float textureAspectRatio = textureWidth / textureHeight;

                vec2 scaledTexCoord = tex_coord0;
                if (viewportAspectRatio > textureAspectRatio) {
                    float scaleFactor = textureAspectRatio / viewportAspectRatio;
                    scaledTexCoord.y = (scaledTexCoord.y - 0.5) * scaleFactor + 0.5;
                } else {
                    float scaleFactor = viewportAspectRatio / textureAspectRatio;
                    scaledTexCoord.x = (scaledTexCoord.x - 0.5) * scaleFactor + 0.5;
                }

                vec2 center = vec2(0.5, 0.5);
                vec2 offset = scaledTexCoord - center;
                float cosAngle = cos(angle);
                float sinAngle = sin(angle);
                vec2 rotatedCoord = vec2(
                    cosAngle * offset.x - sinAngle * offset.y,
                    sinAngle * offset.x + cosAngle * offset.y
                ) + center;

                gl_FragColor = texture2D(texture1, rotatedCoord);
            }

        """
        with self.preview_fbo:
            Rectangle(size=resolution)

    def _java_capture_session_callback(self):
        event = self._java_capture_session_java_callback.getSessionState().name()
        Logger.debug("CALLBACK: capture event %s", event)

        if event == 'CLOSED':
            if self.java_capture_session is not None:
                self.java_capture_session.close()

        elif event == "READY":
            if self.java_capture_session is not None:
                self.java_capture_session.close()
            self.java_capture_session = MyCaptureSessionCallback.camera_capture_session
            self.java_capture_session.setRepeatingRequest(self.java_capture_request.build(),
                                                          None, None)
            Clock.schedule_interval(self._update_preview, 1. / self.fps)

    def _update_preview(self, dt):
        self.java_preview_surface_texture.updateTexImage()
        self.preview_fbo.ask_update()
        self.preview_fbo.draw()
        self.remote_frame_trigger()


class Camera2Widget(Widget):
    _rect_pos = ListProperty([0, 0])
    _rect_size = ListProperty([1, 1])
    camera_angle = NumericProperty()
    fps = NumericProperty(60)
    init = BooleanProperty(True)
    rotation = NumericProperty()
    target_camera = OptionProperty('BACK', options=['FRONT', 'BACK'])
    texture = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = TiltDetector()

    def start_camera(self, instance=None):
        request_permissions([Permission.CAMERA], self._start_camera)

    def _start_camera(self, _, permissions):
        if permissions and permissions[0]:
            self._camera_interface = PyCameraInterface(fps=self.fps, camera_angle=self.camera_angle)
            self._cameras_to_use = {v.facing: v for v in self._camera_interface.cameras}

            if self.target_camera in self._cameras_to_use.keys():
                self.camera_object = self._cameras_to_use[self.target_camera]
                rs = self.camera_object.supported_resolutions
                self.resolution = get_suitable_camera_size(rs)
                self.orientation.enable()
                self.camera_object.open(callback=self._stream_camera_open_callback,
                                        frame_trigger=self.update)
                return

        Logger.warning("Can't connect with %s camera", self.target_camera)

    def stop_camera(self, instance=None):
        if self.camera_object is not None:
            self.orientation.disable()
            self.camera_object.close()
            self.camera_object = None
            self._camera_interface = None
            self._cameras_to_use = {}
            self.texture = None
            collect()

    def shot(self):
        Logger.info("Photo taken")

    @mainthread
    def _stream_camera_open_callback(self, camera, action):
        if action == 'OPENED':
            w, h = self.resolution
            aspect_width = self.width
            aspect_height = self.width * h / w

            if aspect_height < self.height:
                aspect_height = self.height
                aspect_width = aspect_height * w / h

            self._rect_pos = [self.center_x - aspect_width / 2,
                              self.center_y - aspect_height / 2]
            self._rect_size = [aspect_width, aspect_height]
            self.texture = camera.start_preview(self.resolution)

    def update(self):
        self.canvas.ask_update()
        self.rotation = self.orientation.angle
        self.init = False


class Camera2Layout(RelativeLayout):
    camera_angle = NumericProperty()
    fps = NumericProperty(60)

    def start_camera(self):
        self.ids.camera.start_camera()


if __name__ == '__main__':
    class MyApp(App):
        def build(self):
            root = Camera2Layout()
            root.start_camera()
            return root

    MyApp().run()
