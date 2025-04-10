#!/usr/bin/env python3
from pathlib import Path
from typing import Any, Self
import argparse
import sys

import yaml

FADE_DELTA: int = 15
FADE_MIN: int = -80

type_keyframe = dict[int, str]
type_strip = dict[str, Any]

strips: list[type_strip] = []
volume_levels: dict[str, float] = {}
xml_file: str = ''


class Channel():
    def __init__(self, id):
        self.id = id
        self.sequences = []

    def get_left_sequence(self, strip):
        left = None
        for v in self.sequences:
            if v == strip:
                return left
            left = v
        return None


class Strip():
    channel: int = 3
    frame_final_end: int = 0
    type: str = 'AUDIO'
    xml: str = '<EDIT STARTSOURCE={} CHANNEL={} LENGTH={} HARD_LEFT=0 HARD_RIGHT=0 COLOR=0 GROUP_ID=0 USER_TITLE="{}"><FILE SRC="{}"></FILE></EDIT>'  # noqa: E501
    xml_empty: str = '<EDIT STARTSOURCE=0 CHANNEL=0 LENGTH={} HARD_LEFT=0 HARD_RIGHT=0 COLOR=0 GROUP_ID=0></EDIT>'
    xml_fade: str = '<AUTO POSITION={} VALUE={} VALUE1=0 CONTROL_IN_VALUE=0 CONTROL_OUT_VALUE=0 TANGENT_MODE=0></AUTO>'

    def __init__(self, strip, parent):
        self.audio_channels = [1, 0]
        self.fade_in, self.fade_out, self.fade_in_position, self.fade_out_position = tuple(strip['fades'])
        self.filepath = strip['filepath']
        self.flags = strip.get('flags', [])
        self.get_channel(strip, parent)
        self.get_offset_duration_position(strip)
        self.mutes = strip.get('mutes', [])
        self.volume = volume_levels.get(strip['filepath'], 0)
        self.volume_levels = strip.get('volume_levels', [])
        self.add_start_end(parent)

    def __str__(self):
        return '{} | {}'.format(Path(self.filepath).name, self.duration)

    def add_start_end(self, parent):
        self.frame_final_end = parent.frame_final_end + self.position + self.duration
        self.frame_final_start = self.frame_final_end - self.duration

    @property
    def duration(self):
        if self.is_video() and self.channel == 3:
            return self.duration_ - self.fade_out
        else:
            return self.duration_

    def extend_empty(self, left_fade_out, duration):
        if self.is_video() and self.channel == 3:
            duration += left_fade_out
        return duration

    def get_audio_channel(self):
        if self.is_audio():
            return self.audio_channels.pop()
        return 0

    def get_channel(self, strip: type_strip, parent: Self) -> None:
        # Для Cinelerra делим на 2.
        self.channel = strip.get('channel', 0) // 2
        if not self.channel:
            channels = [2, 3]
            if parent.channel in channels:
                channels.remove(parent.channel)
                self.channel = channels[0]
            else:
                self.channel = 2

    def get_delta(self):
        return 800 if self.is_audio() else 1

    def get_fades(self) -> type_keyframe:
        keyframes: type_keyframe = {}

        if self.fade_in_position:
            keyframes |= self.get_volume_level(self.frame_final_start, FADE_MIN)
            position = self.frame_final_start + self.fade_in_position
        else:
            position = self.frame_final_start
        keyframes |= self.get_volume_level(position + self.fade_in // 4, self.volume - FADE_DELTA)
        keyframes |= self.get_volume_level(position, FADE_MIN)
        keyframes |= self.get_volume_level(position + self.fade_in, self.volume)

        if self.fade_out_position:
            keyframes |= self.get_volume_level(self.frame_final_end, FADE_MIN)
            position = self.frame_final_start + self.fade_out_position + self.fade_out
        else:
            position = self.frame_final_end
        keyframes |= self.get_volume_level(position - self.fade_out // 4, self.volume - FADE_DELTA)
        keyframes |= self.get_volume_level(position, FADE_MIN)
        keyframes |= self.get_volume_level(position - self.fade_out, self.volume)

        return keyframes

    def get_mutes(self) -> type_keyframe:
        keyframes: type_keyframe = {}
        position1 = None
        position2 = None
        for v in self.mutes:
            if not position1:
                position1 = v
                continue
            position2 = v
            keyframes |= self.get_volume_level(self.frame_final_start + position1, self.volume)
            keyframes |= self.get_volume_level(self.frame_final_start + position1 + 2, FADE_MIN)
            keyframes |= self.get_volume_level(self.frame_final_start + position2 - 2, FADE_MIN)
            keyframes |= self.get_volume_level(self.frame_final_start + position2, self.volume)
            position1 = None
            position2 = None
        return keyframes

    def get_offset_duration_position(self, strip):
        try:
            self.offset, self.duration_, self.position = strip['offset_duration_position']
        except ValueError:
            self.offset, self.duration_ = strip['offset_duration_position']
            self.position = strip.get('position', -self.fade_in)

    def get_volume_keyframes(self) -> type_keyframe:
        keyframes: type_keyframe = {}
        if 'mute_sound' in self.flags:
            return keyframes
        keyframes |= self.get_fades()
        keyframes |= self.get_mutes()
        keyframes |= self.get_volume_levels_by_keyframes()
        return keyframes

    def get_volume_level(self, position, volume):
        delta = self.get_delta()
        r = {}
        r[position] = self.xml_fade.format(position * delta, volume)
        return r

    def get_volume_levels_by_keyframes(self) -> type_keyframe:
        constants = dict(D=self.volume, FM=FADE_MIN)
        keyframes: type_keyframe = {}
        position = None
        volume = None
        for v in self.volume_levels:
            if position is None:
                position = v
                continue
            volume = constants.get(v, v)
            keyframes |= self.get_volume_level(self.frame_final_start + position, volume)
            position = None
            volume = None
        return keyframes

    def get_xml(self) -> str:
        delta = self.get_delta()
        left = channels[self.channel].get_left_sequence(self)
        left_fade_out = left.fade_out if left else 0
        left_frame_final_end = left.frame_final_end if left else 0
        xml = []
        if (self.is_audio() and 'mute_sound' in self.flags) or (self.is_video() and 'mute_movie' in self.flags):
            if left_frame_final_end != self.frame_final_start:
                duration = self.frame_final_end - left_frame_final_end
                duration = self.extend_empty(left_fade_out, duration)
                return self.xml_empty.format(duration * delta)
            else:
                return ''
        if left_frame_final_end != self.frame_final_start:
            duration = self.frame_final_start - left_frame_final_end
            duration = self.extend_empty(left_fade_out, duration)
            xml.append(self.xml_empty.format(duration * delta))
        channel = self.get_audio_channel()
        xml.append(self.xml.format(self.offset * delta, channel, self.duration * delta, self, self.filepath))
        return '\n'.join(xml)

    def is_audio(self):
        return True if self.type == 'AUDIO' else False

    def is_video(self):
        return not self.is_audio()


channels: dict[int, Channel] = {}
sequences: list[Strip] = []


def get_strips(strips: list[type_strip], parent: type[Strip] | Strip) -> None:
    for i, strip in enumerate(strips):
        if 'filepath' not in strip:
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
        sequences.append(s)

        if s.channel not in channels:
            channels[s.channel] = Channel(id=s.channel)
        channels[s.channel].sequences.append(s)

        if 'strips' in strip:
            get_strips(strip['strips'], parent=s)

        parent = s


def load_yaml_config(file):
    global strips, volume_levels
    with open(file) as f:
        strips = yaml.safe_load(f)
        config = strips[-1]
        if 'volume_levels' in config:
            volume_levels = config['volume_levels']


def main() -> None:
    get_strips(strips, parent=Strip)

    id = None
    type = None
    with open(xml_file) as f:
        for line in f.readlines():
            line = line.strip()

            if line.startswith('<TRACK'):
                type = line.rstrip('>').split('=')[-1]

            if line.startswith('<TITLE>'):
                id = int(line.lstrip('<TITLE>').rstrip('</TITLE>'))

            if line.startswith('</EDITS>'):
                if id in channels:
                    for sequence in channels[id].sequences:
                        sequence.type = type
                        xml = sequence.get_xml()
                        if xml:
                            print(xml)

            if line.startswith('</FADEAUTOS>') and type == 'AUDIO' and id in channels:
                for sequence in channels[id].sequences:
                    keyframes = sequence.get_volume_keyframes()
                    if keyframes:
                        print('\n'.join(keyframes.values()))

            print(line)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('xml', type=str)
    parser.add_argument('strips', type=str)
    args = parser.parse_args()
    load_yaml_config(args.strips)
    xml_file = args.xml
    main()
    sys.exit(0)
