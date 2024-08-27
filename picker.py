from kivy.clock import mainthread
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ListProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner

__all__ = ('ResolutionPicker', 'CameraRSButton')

Builder.load_string('''
<ResolutionPicker>:
    text:(f'{self.selected_resolution[0]} x {self.selected_resolution[1]}' \
            if self.selected_resolution else '')
    values: [f'{res[0]} x {res[1]}' for res in self.available_resolutions]
    background_color: 1, .8, 0, 1
    background_normal: ''
    font_size: dp(9)
    color: 0, 0, 0, 1
    height: dp(30)
    on_submit: self.change_resolution(args[1])
    on_text: self.submit()
    option_cls: 'CameraRSButton'
    size_hint: None, None

<CameraRSButton>:
    font_size: dp(9)
    color: [int(not self.active)] * 3
    height: 30
    size_hint: None, None
    canvas.before:
        Color:
            rgba: (1, .8, 0, .7) if self.active else (0, 0, 0, .5)
        Rectangle:
            size: self.size
            pos: self.pos
''')


class ResolutionPicker(Spinner):
    __events__ = ('on_submit', )

    selected_resolution = ListProperty()
    available_resolutions = ListProperty()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fbind('selected_resolution', self._update_dropdown)
        self.first_run = True

    def change_resolution(self, value):
        self.selected_resolution = value

    @mainthread
    def _update_dropdown(self, *args):
        super()._update_dropdown(*args)
        option_cls = (self.option_cls
                      if not isinstance(self.option_cls, str)
                      else Factory.get(self.option_cls))
        for widget in self._dropdown.container.children:
            if isinstance(widget, option_cls) and widget.text == self.text:
                widget.active = True
                break

    def submit(self):
        try:
            index = self.values.index(self.text)
            if self.first_run:
                self.first_run = False
                return
        except ValueError:
            return

        selected_resolution = self.available_resolutions[index]
        self.selected_resolution = selected_resolution
        self.dispatch('on_submit', selected_resolution)

    def on_submit(self, resolution: list[int]):
        pass


class CameraRSButton(ButtonBehavior, Label):
    active = BooleanProperty(False)


if __name__ == '__main__':
    from kivy.app import App

    class MyApp(App):
        def build(self):
            return ResolutionPicker()

    MyApp().run()
