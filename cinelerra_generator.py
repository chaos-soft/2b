#!/usr/bin/env python3
from typing import Any
import argparse
import sys

import yaml

FADE_MIN: int = -80

type_strip = dict[str, Any]

strips: list[type_strip] = []
volume_levels: dict[str, float] = {}
xml_file: str = ''


class Channel():
    def __init__(self, id):
        self.id = id
        self.sequences = []

    def get_left_sequence(self, strip):
        return get_left_sequence(strip, self.sequences)


class Strip():
    type = 'AUDIO'
    xml = '<EDIT STARTSOURCE={} CHANNEL={} LENGTH={} HARD_LEFT=0 HARD_RIGHT=0 COLOR=0 GROUP_ID=0><FILE SRC="{}"></FILE></EDIT>'  # noqa: E501
    xml_empty = '<EDIT STARTSOURCE=0 CHANNEL=0 LENGTH={} HARD_LEFT=0 HARD_RIGHT=0 COLOR=0 GROUP_ID=0></EDIT>'
    xml_fade = '<AUTO POSITION={} VALUE={} VALUE1=0 CONTROL_IN_VALUE=0 CONTROL_OUT_VALUE=0 TANGENT_MODE=0></AUTO>'

    def __init__(self, strip):
        self.audio_channels = [1, 0]
        self.fade_in, self.fade_out = tuple(strip.get('fades', [0, 0]))
        self.filepath = strip['filepath']
        self.get_channel(strip)
        self.get_offset_duration_position(strip)
        self.mutes = strip.get('mutes', [])
        self.volume = volume_levels.get(strip['filepath'], 0)
        self.add_start_end()

    def add_start_end(self):
        last = get_last_sequence()
        if last:
            self.frame_final_end = last.frame_final_end + self.position + self.duration
        else:
            self.frame_final_end = self.position + self.duration
        self.frame_final_start = self.frame_final_end - self.duration

    @property
    def duration(self):
        if self.type == 'VIDEO' and self.channel == 3:
            return self.duration_ - self.fade_out
        else:
            return self.duration_

    def extend_empty(self, left_fade_out, duration):
        if self.type == 'VIDEO' and self.channel == 3:
            duration += left_fade_out
        return duration

    def get_audio_channel(self):
        if self.type == 'AUDIO':
            return self.audio_channels.pop()
        return 0

    def get_channel(self, strip: type_strip) -> None:
        # Для Cinelerra делим на 2.
        self.channel = strip.get('channel', 0) // 2
        if not self.channel:
            last = get_last_sequence()
            if not last:
                self.channel = 2
                return None
            channels = [2, 3]
            if last.channel in channels:
                channels.remove(last.channel)
                self.channel = channels[0]
            else:
                self.channel = 2

    def get_delta(self):
        return 800 if self.type == 'AUDIO' else 1

    def get_fades_mutes(self):
        fades = {}

        fades |= self.get_volume_level(self.frame_final_start, FADE_MIN)
        fades |= self.get_volume_level(self.frame_final_start + self.fade_in // 4, self.volume - 10)
        fades |= self.get_volume_level(self.frame_final_start + self.fade_in, self.volume)

        position1 = None
        position2 = None
        for v in self.mutes:
            if not position1:
                position1 = v
                continue
            position2 = v
            fades |= self.get_volume_level(self.frame_final_start + position1, self.volume)
            fades |= self.get_volume_level(self.frame_final_start + position1 + 2, FADE_MIN)
            fades |= self.get_volume_level(self.frame_final_start + position2 - 2, FADE_MIN)
            fades |= self.get_volume_level(self.frame_final_start + position2, self.volume)
            position1 = None
            position2 = None

        fades |= self.get_volume_level(self.frame_final_end, FADE_MIN)
        fades |= self.get_volume_level(self.frame_final_end - self.fade_out // 4, self.volume - 10)
        fades |= self.get_volume_level(self.frame_final_end - self.fade_out, self.volume)

        return '\n'.join(fades.values())

    def get_offset_duration_position(self, strip):
        try:
            self.offset, self.duration_, self.position = strip['offset_duration_position']
        except ValueError:
            self.offset, self.duration_ = strip['offset_duration_position']
            self.position = strip.get('position', -self.fade_in)

    def get_volume_level(self, position, volume):
        delta = self.get_delta()
        position -= 1
        r = {}
        r[position] = self.xml_fade.format(position * delta, volume)
        return r

    def get_xml(self):
        delta = self.get_delta()
        left = channels[self.channel].get_left_sequence(self)
        left_fade_out = left.fade_out if left else 0
        left_frame_final_end = left.frame_final_end if left else 1
        xml = []
        if left_frame_final_end != self.frame_final_start:
            duration = self.frame_final_start - left_frame_final_end
            duration = self.extend_empty(left_fade_out, duration)
            xml.append(self.xml_empty.format(duration * delta))
        channel = self.get_audio_channel()
        xml.append(self.xml.format(self.offset * delta, channel, self.duration * delta, self.filepath))
        return '\n'.join(xml)


channels: dict[int, Channel] = {}
sequences: list[Strip] = []


def get_last_sequence():
    try:
        return sequences[-1]
    except IndexError:
        return None


def get_left_sequence(strip, sequences=sequences):
    left = None
    for v in sequences:
        if v == strip:
            return left
        left = v
    return None


def load_yaml_config(file):
    global strips, volume_levels
    with open(file) as f:
        strips = yaml.safe_load(f)
        config = strips[-1]
        if 'volume_levels' in config:
            volume_levels = config['volume_levels']


def main():
    for i, strip in enumerate(strips):
        if 'filepath' not in strip:
            continue

        strip['fades'] = strip.get('fades', [0, 0])
        try:
            strip['fades'][0] = strips[i - 1]['crossfade']
        except (IndexError, KeyError):
            pass
        try:
            strip['fades'][1] = strips[i + 1]['crossfade']
        except (IndexError, KeyError):
            pass
        s = Strip(strip)
        sequences.append(s)

        if s.channel not in channels:
            channels[s.channel] = Channel(id=s.channel)
        channels[s.channel].sequences.append(s)

    id = None
    is_fade = False
    type = None
    with open(xml_file) as f:
        for line in f.readlines():
            line = line.strip()
            print(line)

            if line.startswith('<TRACK'):
                type = line.rstrip('>').split('=')[-1]

            if line.startswith('<TITLE'):
                id = int(line.lstrip('<TITLE>').rstrip('</TITLE>'))

            if line.startswith('<EDITS'):
                if id in channels:
                    for sequence in channels[id].sequences:
                        sequence.type = type
                        print(sequence.get_xml())

            if line.startswith('<FADEAUTOS') and not is_fade and type == 'AUDIO':
                is_fade = True
            elif is_fade:
                is_fade = False
                if id in channels:
                    for sequence in channels[id].sequences:
                        print(sequence.get_fades_mutes())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('xml', type=str)
    parser.add_argument('strips', type=str)
    args = parser.parse_args()
    load_yaml_config(args.strips)
    xml_file = args.xml
    main()
    sys.exit(0)
