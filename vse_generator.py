from typing import Any, Self

import bpy
import yaml

FADE_MIN: int = 0

type_strip = dict[str, Any]

strips: list[type_strip] = []
volume_levels: dict[str, float] = {}


class BuildStripsOperator(bpy.types.Operator):
    bl_idname = 'wm.build_strips'
    bl_label = 'Build Strips'

    def execute(self, context):
        load_yaml_config()
        get_strips(strips, parent=Strip)
        bpy.ops.sequencer.select_all(action='SELECT')
        print('FINISHED')
        return {'FINISHED'}


class BuildStripsPanel(bpy.types.Panel):
    bl_category = 'Tools'
    bl_context = 'object'
    bl_idname = 'OBJECT_PT_build_strips'
    bl_label = 'Tools'
    bl_region_type = 'UI'
    bl_space_type = 'SEQUENCE_EDITOR'

    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.prop(context.scene, 'create_fades')
        row = layout.row()
        row.operator('wm.build_strips')


class Strip():
    channel: int = 6
    frame_final_end: int = 0
    name: int = 0

    def __init__(self, strip, parent):
        self.flags = strip.get('flags', [])
        self.name = parent.name + 1
        if 'mute_blender' in self.flags:
            return None
        self.fade_in, self.fade_out, self.fade_in_position, self.fade_out_position = tuple(strip['fades'])
        self.filepath = strip['filepath']
        self.get_channel(strip, parent)
        self.get_offset_duration_position(strip, parent)
        self.volume = volume_levels.get(strip['filepath'], 1)
        self.volume_levels = strip.get('volume_levels', [])
        self.movie_strip_add()
        self.find_strips()
        self.set_start_duration()
        self.set_channel_flags()
        if 'mute_sound' not in self.flags and bpy.context.scene.create_fades:
            self.set_fades()
            self.set_volume_levels_by_keyframes()
        self.frame_final_end = self.s.frame_final_end

    def find_strips(self):
        self.m = bpy.context.sequences[-1]
        if self.m.type == 'SOUND':
            self.m = bpy.context.sequences[-2]
            self.s = bpy.context.sequences[-1]
        else:
            self.s = bpy.context.sequences[-2]
        self.m.name = f'm{self.name}'
        self.s.name = f's{self.name}'

    def get_channel(self, strip: type_strip, parent: Self) -> None:
        self.channel = strip.get('channel', 0)
        if not self.channel:
            channels = [4, 6]
            if parent.channel in channels:
                channels.remove(parent.channel)
                self.channel = channels[0]
            else:
                self.channel = 4

    def get_offset_duration_position(self, strip, parent):
        try:
            self.offset, self.duration, self.position = strip['offset_duration_position']
        except ValueError:
            self.offset, self.duration = strip['offset_duration_position']
            self.position = strip.get('position', -self.fade_in)
        self.position += parent.frame_final_end

    def movie_strip_add(self):
        bpy.ops.sequencer.movie_strip_add(
            channel=100,
            filepath=self.filepath,
            frame_start=0,
            relative_path=False,
            use_framerate=False,
        )
        if self.offset:
            bpy.ops.sequencer.split(frame=self.offset, side='LEFT')
            bpy.ops.sequencer.delete()

    def set_channel_flags(self):
        self.m.channel = self.channel
        if 'mute_movie' in self.flags:
            self.m.mute = True

        self.s.channel = self.channel - 1
        if 'mute_sound' in self.flags:
            self.s.mute = True

    def set_fades(self):
        if self.fade_in != 0 or self.volume != 1:
            if self.fade_in_position:
                position = self.s.frame_final_start + self.fade_in_position
            else:
                position = self.s.frame_final_start
            self.set_volume_level(position, 0)
            self.set_volume_level(position + self.fade_in, self.volume)

        if self.fade_out != 0 or self.volume != 1:
            if self.fade_out_position:
                position = self.s.frame_final_start + self.fade_out_position + self.fade_out
            else:
                position = self.s.frame_final_end
            self.set_volume_level(position, 0)
            self.set_volume_level(position - self.fade_out, self.volume)

    def set_start_duration(self):
        self.m.frame_start = self.position - self.m.frame_offset_start
        if self.duration:
            if self.channel == 6:
                self.m.frame_final_duration = self.duration - self.fade_out
            else:
                self.m.frame_final_duration = self.duration

        self.s.frame_start = self.position - self.s.frame_offset_start
        if self.duration:
            self.s.frame_final_duration = self.duration

    def set_volume_level(self, position, volume):
        self.s.volume = volume
        self.s.keyframe_insert('volume', frame=position)

    def set_volume_levels_by_keyframes(self):
        constants = dict(D=self.volume, FM=FADE_MIN)
        position = None
        volume = None
        for v in self.volume_levels:
            if position is None:
                position = v
                continue
            volume = constants.get(v, v)
            self.set_volume_level(self.s.frame_final_start + position, volume)
            position = None
            volume = None


def get_strips(strips: list[type_strip], parent: Strip) -> None:
    for i, strip in enumerate(strips):
        if 'filepath' not in strip:
            continue
        name = f's{parent.name + 1}'
        if name in bpy.context.scene.sequence_editor.sequences_all:
            sequence = bpy.context.scene.sequence_editor.sequences_all[name]
            strip['flags'] = ['mute_blender']
            s = Strip(strip, parent=parent)
            s.channel = sequence.channel
            s.frame_final_end = sequence.frame_final_end
            parent = s
            continue

        strip['fades'] = strip.get('fades', [0, 0])
        if len(strip['fades']) == 2:
            strip['fades'] += [0, 0]
        try:
            strip['fades'][0] = strips[i - 1]['crossfade']
        except (IndexError, KeyError):
            pass
        try:
            strip['fades'][1] = strips[i + 1]['crossfade']
        except (IndexError, KeyError):
            pass
        s = Strip(strip, parent=parent)

        parent = s
        print(s.name, s.filepath)

        if 'strips' in strip:
            get_strips(strip['strips'], parent=parent)


def load_yaml_config():
    global strips, volume_levels
    path = bpy.path.abspath('//strips.yml')
    with open(path) as f:
        strips = yaml.safe_load(f)
        config = strips[-1]
        if 'volume_levels' in config:
            volume_levels = config['volume_levels']


def register():
    bpy.utils.register_class(BuildStripsOperator)
    bpy.utils.register_class(BuildStripsPanel)
    bpy.types.Scene.create_fades = bpy.props.BoolProperty(
        default=True,
        name='Create Fades',
    )


def unregister():
    bpy.utils.unregister_class(BuildStripsOperator)
    bpy.utils.unregister_class(BuildStripsPanel)
    del bpy.types.Scene.create_fades


if __name__ == '__main__':
    register()
