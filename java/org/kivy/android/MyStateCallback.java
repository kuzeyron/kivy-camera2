package org.kivy.android;

import android.hardware.camera2.CameraDevice;
import java.lang.Runnable;
import android.util.Log;


public class MyStateCallback extends CameraDevice.StateCallback {
	private static final String TAG = "pythonMyStateCallback";

    Runnable callback;

    public enum CameraActions {
        CLOSED,
        DISCONNECTED,
        OPENED,
        ERROR,
        UNKNOWN
    };

    private CameraDevice camera_device = null;
    private CameraActions camera_action = CameraActions.UNKNOWN;
    private String captureEvent = "UNKNOWN";
    public static int camera_error = 0;

    public MyStateCallback(Runnable the_callback) {
        callback = the_callback;
    }

    public void onClosed(CameraDevice cam) {
        Log.v(TAG, "onClosed");
        this.camera_device = cam;
        this.camera_action = CameraActions.CLOSED;
        this.callback.run();
    }

    public void onDisconnected(CameraDevice cam) {
        Log.v(TAG, "onDisconnected");
        this.camera_device = cam;
        this.camera_action = CameraActions.DISCONNECTED;
        this.callback.run();
    }

    public void onOpened(CameraDevice cam) {
        Log.v(TAG, "onOpened");
        this.camera_device = cam;
        this.camera_action = CameraActions.OPENED;
        this.callback.run();
    }

    @Override
    public void onError(CameraDevice cam, int error) {
        Log.v(TAG, "onError");
        this.camera_device = cam;
        this.camera_action = CameraActions.ERROR;
        this.camera_error = error;
        this.callback.run();
    }

    public CameraActions getCameraAction() {
        return camera_action;
    }

    public CameraDevice getCameraDevice() {
        return camera_device;
    }

    public String getCaptureEvent() {
        return captureEvent;
    }
}
