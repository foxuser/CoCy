"""
..
   This file is part of the CoCy program.
   Copyright (C) 2011 Michael N. Lipp
   
   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
from cocy.upnp.adapters.adapter import upnp_service, UPnPServiceController,\
    upnp_state, Notification
from circuits_bricks.app.logger import Log
import logging
from time import time
from circuits_bricks.core.timers import Timer
from circuits.core.events import Event
from circuits.core.handlers import handler
from StringIO import StringIO
from xml.etree.ElementTree import Element, QName, ElementTree, SubElement
from cocy.upnp import UPNP_AVT_EVENT_NS

class UPnPCombinedEventsServiceController(UPnPServiceController):
    
    def __init__(self, adapter, device_path, service, service_id):
        super(UPnPCombinedEventsServiceController, self).__init__\
            (adapter, device_path, service, service_id)
        self._changes = dict()
        self._updates_locked = False
        
    @upnp_state(evented_by=None)
    def LastChange(self):
        writer = StringIO()
        root = Element(QName(UPNP_AVT_EVENT_NS, "Event"))
        inst = SubElement(root, QName(UPNP_AVT_EVENT_NS, "InstanceID"), 
                                      { "val": "0" })
        for name, value in self._changes.items():
            SubElement(inst, QName(UPNP_AVT_EVENT_NS, name), { "val": value })
        ElementTree(root).write(writer, encoding="utf-8")
        return writer.getvalue()

    def addChange(self, variable, value):
        self._changes[variable] = value
        if not self._updates_locked:
            self._send_changes()

    def _send_changes(self):
        if len(self._changes) == 0:
            return
        self.fire(Notification({ "LastChange": self.LastChange() }),
                  self.notification_channel)
        self._changes.clear()
        Timer(0.2, Event.create("UnlockUpdates"), self).register(self)
        self._updates_locked = True

    @handler("unlock_updates")
    def _on_unlock_updates(self, *args):
        self._updates_locked = False
        self._send_changes()


class RenderingController(UPnPServiceController):
    
    volume = 25
    
    def __init__(self, adapter, device_path, service, service_id):
        super(RenderingController, self).__init__\
            (adapter, device_path, service, service_id)
        self._target = None

    @upnp_service
    def GetVolume(self, **kwargs):
        self.fire(Log(logging.DEBUG, "GetVolume called"), "logger")
        return [("CurrentVolume", str(self.volume))]


class ConnectionManagerController(UPnPServiceController):
    
    def __init__(self, adapter, device_path, service, service_id):
        super(ConnectionManagerController, self).__init__\
            (adapter, device_path, service, service_id)
        self._target = None

    @upnp_service
    def GetProtocolInfo(self, **kwargs):
        self.fire(Log(logging.DEBUG, "GetProtocolInfo called"), "logger")
        return [("Source", ""),
                ("Sink", "http-get:*:audio/mpeg:*")]


class AVTransportController(UPnPCombinedEventsServiceController):
    
    def __init__(self, adapter, device_path, service, service_id):
        super(AVTransportController, self).__init__\
            (adapter, device_path, service, service_id)
        self._provider = adapter.provider
        self._target = None
        self._transport_state = "STOPPED"
        @handler("provider_updated", channel=self._provider.channel)
        def _on_provider_updated_handler(self, provider, changed):
            if provider != self._provider:
                return
            self._map_changes(changed)
        self.addHandler(_on_provider_updated_handler)

    def _format_duration(self, duration):
        return "%d:%02d:%02d" % (int(duration / 3600), 
                                 int(int(duration) % 3600 / 60),
                                 int(duration) % 60)

    def _map_changes(self, changed):
        for name, value in changed.items():
            if name == "source":
                self.addChange("AVTransportURI", value)
                self.addChange("CurrentTrackURI", value)
                continue
            if name == "source_meta_data":
                self.addChange("AVTransportURIMetaData", value)
                self.addChange("CurrentTrackMetaData", value)
                continue
            if name == "state":
                if value == "PLAYING":
                    self._transport_state = "PLAYING"
                    self.addChange("TransportState", self._transport_state)
                elif value == "IDLE":
                    self._transport_state = "STOPPED"
                    self.addChange("TransportState", self._transport_state)
                elif value == "PAUSED":
                    self._transport_state = "PAUSED_PLAYBACK"
                    self.addChange("TransportState", self._transport_state)
                continue
        
    @upnp_service
    def GetTransportInfo(self, **kwargs):
        self.fire(Log(logging.DEBUG, "GetTransportInfo called"), "logger")
        return [("CurrentTransportState", self._transport_state),
                ("CurrentTransportStatus", "OK"),
                ("CurrentSpeed", "1")]

    @upnp_service
    def GetMediaInfo(self, **kwargs):
        self.fire(Log(logging.DEBUG, "GetMediaInfo called"), "logger")
        return [("NrTracks", self._provider.tracks),
                ("MediaDuration", "0:00:00"),
                ("CurrentURI", self._provider.source),
                ("CurrentURIMetaData", "NOT_IMPLEMENTED" \
                 if self._provider.source_meta_data is None \
                 else self._provider.source_meta_data),
                ("NextURI", "NOT_IMPLEMENTED"),
                ("NextURIMetaData", "NOT_IMPLEMENTED"),
                ("PlayMedium", "NONE"),
                ("RecordMedium", "NOT_IMPLEMENTED"),
                ("WriteStatus", "NOT_IMPLEMENTED")]

    @upnp_service
    def GetPositionInfo(self, **kwargs):
        rel_pos = self._provider.current_position()
        info = [("Track", self._provider.current_track),
                ("TrackDuration", "NOT_IMPLEMENTED" \
                 if self._provider.current_track_duration is None \
                 else self._format_duration \
                    (self._provider.current_track_duration)),
                ("TrackMetaData", "NOT_IMPLEMENTED" \
                 if self._provider.source_meta_data is None \
                 else self._provider.source_meta_data),
                ("TrackURI", self._provider.source),
                ("RelTime", "NOT_IMPLEMENTED" if rel_pos is None \
                 else self._format_duration(rel_pos)),
                ("AbsTime", "NOT_IMPLEMENTED"),
                ("RelCount", 2147483647),
                ("AbsCount", 2147483647)]
        return info

    @upnp_service
    def SetAVTransportURI(self, **kwargs):
        self.fire(Log(logging.DEBUG, 'AV Transport URI set to '
                      + kwargs["CurrentURI"]), "logger")
        self.fire(Event.create("Load", kwargs["CurrentURI"], 
                               kwargs["CurrentURIMetaData"]),
                  self.parent.provider.channel)
        return []
    
    @upnp_service
    def Play(self, **kwargs):
        self.fire(Log(logging.DEBUG, "Play called"), "logger")
        self.fire(Event.create("Play"),
                  self.parent.provider.channel)
        return []
    
    @upnp_service
    def Pause(self, **kwargs):
        self.fire(Log(logging.DEBUG, "Pause called"), "logger")
        self.fire(Event.create("Pause"),
                  self.parent.provider.channel)
        return []
    
    @upnp_service
    def Stop(self, **kwargs):
        self.fire(Log(logging.DEBUG, "Stop called"), "logger")
        self.fire(Event.create("Stop"),
                  self.parent.provider.channel)
        return []
    
    