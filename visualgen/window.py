import glfw


class WindowError(Exception):
    pass


def create_fullscreen(title: str):
    if not glfw.init():
        raise WindowError("could not initialize GLFW")
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)  # required on macOS
    glfw.window_hint(glfw.AUTO_ICONIFY, glfw.FALSE)

    monitor = glfw.get_primary_monitor()
    mode = glfw.get_video_mode(monitor)
    win = glfw.create_window(mode.size.width, mode.size.height, title, monitor, None)
    if not win:
        glfw.terminate()
        raise WindowError("could not create fullscreen window")
    glfw.make_context_current(win)
    glfw.swap_interval(1)  # vsync on: the render loop ticks once per refresh
    width, height = glfw.get_framebuffer_size(win)
    return win, (width, height)


def should_close(win) -> bool:
    return bool(glfw.window_should_close(win))


def close(win) -> None:
    glfw.set_window_should_close(win, True)


def terminate() -> None:
    glfw.terminate()
