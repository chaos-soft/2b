import bpy
import yaml

filepath_mute = ''
filepath_offset = 0
strips = []
volume_levels = {}


class BuildStripsOperator(bpy.types.Operator):
    bl_idname = 'wm.build_strips'
    bl_label = 'Build Strips'

    def execute(self, context):
        load_yaml_config()
        i = 1
        for idx, strip in enumerate(strips):
            if 'filepath' not in strip and 'filepath_sound' not in strip:
                continue
            if f'm{i}' in context.scene.sequence_editor.sequences_all or \
               f's{i}' in context.scene.sequence_editor.sequences_all:
                i += 1
                continue

            flags = strip.get('flags', [])

            fades = strip.get('fades', [0, 0])
            try:
                fades[0] = strips[idx - 1]['crossfade']
            except (IndexError, KeyError):
                pass
            try:
                fades[1] = strips[idx + 1]['crossfade']
            except (IndexError, KeyError):
                pass

            try:
                offset, duration, position = strip['offset_duration_position']
            except ValueError:
                offset, duration = strip['offset_duration_position']
                position = strip.get('position', -fades[0])
            name = strip.get('position_by', f's{i - 1}')
            if name in context.scene.sequence_editor.sequences_all:
                s = context.scene.sequence_editor.sequences_all[name]
                position += s.frame_final_end

            channel = strip.get('channel')
            if not channel:
                name = f'm{i - 1}'
                if name in context.scene.sequence_editor.sequences_all:
                    m = context.scene.sequence_editor.sequences_all[name]
                    channels = [4, 6]
                    if m.channel in channels:
                        channels.remove(m.channel)
                        channel = channels[0]
                    else:
                        channel = 4
                else:
                    channel = 4

            if 'filepath' in strip:
                bpy.ops.sequencer.movie_strip_add(
                    channel=100,
                    filepath=strip['filepath'],
                    frame_start=0,
                    relative_path=False,
                )
                if offset:
                    bpy.ops.sequencer.split(frame=offset, side='LEFT')
                    bpy.ops.sequencer.delete()

                m = context.sequences[-1]
                if m.type == 'SOUND':
                    m = context.sequences[-2]
                    s = context.sequences[-1]
                else:
                    s = context.sequences[-2]
                m.name = f'm{i}'
                s.name = f's{i}'

                m.frame_start = position - m.frame_offset_start
                if duration:
                    if channel == 6:
                        m.frame_final_duration = duration - fades[1]
                    else:
                        m.frame_final_duration = duration
                m.channel = channel
                if 'mute_movie' in flags:
                    m.mute = True

                s.frame_start = position - s.frame_offset_start
                if duration:
                    s.frame_final_duration = duration
                s.channel = channel - 1
            elif 'filepath_sound' in strip:
                s = sound_strip_add(
                    strip['filepath_sound'],
                    channel=channel,
                    name=f's{i}',
                    offset=offset,
                    duration=duration,
                    position=position,
                )
                strip['filepath'] = strip['filepath_sound']

            if 'mute_sound' in flags:
                s.mute = True
            else:
                set_fades(s, fades=fades, volume=volume_levels.get(strip['filepath'], 1))
                set_mutes(s, mutes=strip.get('mutes', []), volume=volume_levels.get(strip['filepath'], 1))
                set_volume_levels_by_keyframes(s, volume_levels=strip.get('volume_levels', []))

            print(i, strip.get('filepath', '') or strip.get('filepath_sound', ''))
            i += 1
        bpy.ops.sequencer.select_all(action='SELECT')
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
        row.operator('wm.build_strips')


def load_yaml_config():
    global filepath_mute, filepath_offset, strips, volume_levels
    path = bpy.path.abspath('//strips.yml')
    try:
        with open(path) as f:
            strips = yaml.safe_load(f)
            config = strips[-1]
            if 'filepath_mute' in config:
                filepath_mute = config['filepath_mute']
                filepath_offset = config['filepath_offset']
            if 'volume_levels' in config:
                volume_levels = config['volume_levels']
    except OSError:
        pass


def register():
    bpy.utils.register_class(BuildStripsOperator)
    bpy.utils.register_class(BuildStripsPanel)


def set_fades(strip, fades, volume):
    if fades[0] != 0 or volume != 1:
        set_volume_level(strip, strip.frame_final_start, 0)
        set_volume_level(strip, strip.frame_final_start + fades[0], volume)
    if fades[1] != 0 or volume != 1:
        set_volume_level(strip, strip.frame_final_end, 0)
        set_volume_level(strip, strip.frame_final_end - fades[1], volume)


def set_mutes(strip, mutes, volume):
    position1 = None
    position2 = None
    for v in mutes:
        if not position1:
            position1 = v
            continue
        position2 = v
        set_volume_level(strip, strip.frame_final_start + position1, volume)
        set_volume_level(strip, strip.frame_final_start + position1 + 2, 0)
        set_volume_level(strip, strip.frame_final_start + position2 - 2, 0)
        set_volume_level(strip, strip.frame_final_start + position2, volume)
        if filepath_mute:
            s = sound_strip_add(
                filepath_mute,
                channel=14,
                name='mute',
                offset=filepath_offset,
                duration=position2 - position1,
                position=strip.frame_final_start + position1,
            )
            set_fades(s, fades=[2, 2], volume=volume_levels.get(filepath_mute, 1))
        position1 = None
        position2 = None


def set_volume_level(strip, position, volume):
    strip.volume = volume
    strip.keyframe_insert('volume', frame=position)


def set_volume_levels_by_keyframes(strip, volume_levels):
    position = None
    volume = None
    for v in volume_levels:
        if position is None:
            position = v
            continue
        volume = v
        set_volume_level(strip, strip.frame_final_start + position, volume)
        position = None
        volume = None


def sound_strip_add(filepath, channel, name, offset, duration, position):
    bpy.ops.sequencer.sound_strip_add(
        channel=100,
        filepath=filepath,
        frame_start=0,
        relative_path=False,
    )
    bpy.ops.sequencer.split(frame=offset, side='LEFT')
    bpy.ops.sequencer.delete()
    s = bpy.context.sequences[-1]
    s.name = name
    s.frame_start = position - s.frame_offset_start
    if duration:
        s.frame_final_duration = duration
    s.channel = channel - 1
    return s


def unregister():
    bpy.utils.unregister_class(BuildStripsOperator)
    bpy.utils.unregister_class(BuildStripsPanel)


if __name__ == '__main__':
    register()
