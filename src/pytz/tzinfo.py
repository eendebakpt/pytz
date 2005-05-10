#!/usr/bin/env python
'''
$Id: tzinfo.py,v 1.4 2004/07/23 23:24:45 zenzen Exp $
'''

__rcs_id__  = '$Id: tzinfo.py,v 1.4 2004/07/23 23:24:45 zenzen Exp $'
__version__ = '$Revision: 1.4 $'[11:-2]

from datetime import datetime, timedelta, tzinfo
from bisect import bisect_right
from sets import Set

_timedelta_cache = {}
def memorized_timedelta(seconds):
    '''Create only one instance of each distinct timedelta'''
    try:
        return _timedelta_cache[seconds]
    except KeyError:
        delta = timedelta(seconds=seconds)
        _timedelta_cache[seconds] = delta
        return delta

_datetime_cache = {}
def memorized_datetime(*args):
    '''Create only one instance of each distinct datetime'''
    try:
        return _datetime_cache[args]
    except KeyError:
        dt = datetime(*args)
        _datetime_cache[args] = dt
        return dt

_ttinfo_cache = {}
def memorized_ttinfo(*args):
    '''Create only one instance of each distinct tuple'''
    try:
        return _ttinfo_cache[args]
    except KeyError:
        ttinfo = (
                memorized_timedelta(args[0]),
                memorized_timedelta(args[1]),
                args[2]
                )
        _ttinfo_cache[args] = ttinfo
        return ttinfo

_notime = memorized_timedelta(0)

class BaseTzInfo(tzinfo):
    # Overridden in subclass
    _utcoffset = None
    _tzname = None
    _zone = None

    def __str__(self):
        return self._zone
    

class StaticTzInfo(BaseTzInfo):
    def fromutc(self, dt):
        '''See datetime.tzinfo.fromutc'''
        return (dt + self._utcoffset).replace(tzinfo=self)
    
    def utcoffset(self,dt):
        '''See datetime.tzinfo.utcoffset'''
        return self._utcoffset

    def dst(self,dt):
        '''See datetime.tzinfo.dst'''
        return _notime

    def tzname(self,dt):
        '''See datetime.tzinfo.tzname'''
        return self._tzname

    def normalize(self, dt, is_dst=False):
        '''Correct the timezone information on the given datetime'''
        return dt.replace(tzinfo=self)

    def __repr__(self):
        return '<StaticTzInfo %r>' % (self._zone,)


class DstTzInfo(BaseTzInfo):
    # Overridden in subclass
    _utc_transition_times = None # Sorted list of DST transition times in UTC
    _transition_info = None # [(utcoffset, dstoffset, tzname)] corresponding
                            # to _utc_transition_times entries
    _zone = None

    # Set in __init__
    _tzinfos = None
    _dst = None # DST offset

    def __init__(self, _inf=None, _tzinfos=None):
        if _inf:
            self._tzinfos = _tzinfos
            self._utcoffset, self._dst, self._tzname = _inf
        else:
            _tzinfos = {}
            self._tzinfos = _tzinfos
            self._utcoffset, self._dst, self._tzname = self._transition_info[0]
            _tzinfos[self._transition_info[0]] = self
            for inf in self._transition_info[1:]:
                if not _tzinfos.has_key(inf):
                    _tzinfos[inf] = self.__class__(inf, _tzinfos)

    def fromutc(self, dt):
        '''See datetime.tzinfo.fromutc'''
        dt = dt.replace(tzinfo=None)
        idx = max(0, bisect_right(self._utc_transition_times, dt) - 1)
        inf = self._transition_info[idx]
        return (dt + inf[0]).replace(tzinfo=self._tzinfos[inf])

    def normalize(self, dt, is_dst=False):
        '''Correct the timezone information on the given datetime

        If date arithmetic crosses DST boundaries, the tzinfo
        is not magically adjusted. This method normalizes the
        tzinfo to the correct one.

        To test, first we need to do some setup

        >>> import pytz
        >>> from datetime import datetime, timedelta
        >>> utc = pytz.timezone('UTC')
        >>> eastern = pytz.timezone('US/Eastern')
        >>> fmt = '%Y-%m-%d %H:%M:%S %Z (%z)'

        We next create a datetime right on an end-of-DST transition point,
        the instant when the wallclocks are wound back one hour.

        >>> utc_dt = datetime(2002, 10, 27, 6, 0, 0, tzinfo=utc)
        >>> loc_dt = utc_dt.astimezone(eastern)
        >>> loc_dt.strftime(fmt)
        '2002-10-27 01:00:00 EST (-0500)'

        Now, if we subtract a few minutes from it, note that the timezone
        information has not changed.

        >>> before = loc_dt - timedelta(minutes=10)
        >>> before.strftime(fmt)
        '2002-10-27 00:50:00 EST (-0500)'

        But we can fix that by calling the normalize method

        >>> before = eastern.normalize(before)
        >>> before.strftime(fmt)
        '2002-10-27 01:50:00 EDT (-0400)'

        This method is also required to correctly construct local times.
        is_dst is used to determine the correct timezone in the ambigous
        period at the end of daylight savings time.
        
        >>> amdam = pytz.timezone('Europe/Amsterdam')
        >>> loc_dt  = datetime(2004, 10, 31, 2, 0, 0)
        >>> loc_dt1 = amdam.normalize(loc_dt, is_dst=True)
        >>> loc_dt2 = amdam.normalize(loc_dt, is_dst=False)
        >>> loc_dt1.strftime(fmt)
        '2004-10-31 02:00:00 CEST (+0200)'
        >>> loc_dt2.strftime(fmt)
        '2004-10-31 02:00:00 CET (+0100)'
        >>> str(loc_dt2 - loc_dt1)
        '1:00:00'

        Use is_dst=None to raise an AmbiguousTimeError for ambiguous
        times at the end of daylight savings

        >>> try:
        ...     loc_dt1 = amdam.normalize(loc_dt, is_dst=None)
        ... except AmbiguousTimeError:
        ...     print 'Oops'
        Oops

        is_dst defaults to False
        
        >>> amdam.normalize(loc_dt) == amdam.normalize(loc_dt, False)
        True

        '''
        if dt.tzinfo:
            # Convert dt in localtime to UTC
            offset = dt.tzinfo._utcoffset
            dt = dt.replace(tzinfo=None)
            dt = dt - offset
            # convert it back, and return it
            return self.fromutc(dt)

        # Find the possibly correct timezones. We probably just have one,
        # but we might end up with two if we are in the end-of-DST
        # transition period. Or possibly more in some particularly confused
        # location...
        possible_loc_dt = Set()
        for tzinfo in self._tzinfos.values():
            loc_dt = tzinfo.normalize(dt.replace(tzinfo=tzinfo))
            if loc_dt.replace(tzinfo=None) == dt:
                possible_loc_dt.add(loc_dt)

        if len(possible_loc_dt) == 1:
            return possible_loc_dt.pop()

        # If told to be strict, raise an exception since we have an
        # ambiguous case
        if is_dst is None:
            raise AmbiguousTimeError(dt, self)

        # Filter out the possiblilities that don't match the requested
        # is_dst
        filtered_possible_loc_dt = [
            p for p in possible_loc_dt
                if bool(p.tzinfo._dst) == is_dst
            ]

        # Hopefully we only have one possibility left. Return it.
        if len(filtered_possible_loc_dt) == 1:
            return filtered_possible_loc_dt[0]

        if len(filtered_possible_loc_dt) == 0:
            filtered_possible_loc_dt = list(possible_loc_dt)

        # If we get this far, we have in a wierd timezone transition
        # where the clocks have been wound back but is_dst is the same
        # in both (eg. Europe/Warsaw 1915 when they switched to CET).
        # At this point, we just have to guess unless we allow more
        # hints to be passed in (such as the UTC offset or abbreviation),
        # but that is just getting silly.
        #
        # Choose the earliest (by UTC) applicable timezone.
        def mycmp(a,b):
            return cmp(
                    a.replace(tzinfo=None) - a.tzinfo._utcoffset,
                    b.replace(tzinfo=None) - b.tzinfo._utcoffset,
                    )
        filtered_possible_loc_dt.sort(mycmp)
        return filtered_possible_loc_dt[0]
        
    def utcoffset(self, dt):
        '''See datetime.tzinfo.utcoffset'''
        return self._utcoffset

    def dst(self, dt):
        '''See datetime.tzinfo.dst'''
        return self._dst

    def tzname(self, dt):
        '''See datetime.tzinfo.tzname'''
        return self._tzname

    def __repr__(self):
        if self._dst:
            dst = 'DST'
        else:
            dst = 'STD'
        if self._utcoffset > _notime:
            return '<DstTzInfo %r %s+%s %s>' % (
                    self._zone, self._tzname, self._utcoffset, dst
                )
        else:
            return '<DstTzInfo %r %s%s %s>' % (
                    self._zone, self._tzname, self._utcoffset, dst
                )

class AmbiguousTimeError(Exception):
    '''Exception raised when attempting to create an ambiguous wallclock time.

    At the end of a DST transition period, a particular wallclock time will
    occur twice (once before the clocks are set back, once after). Both
    possibilities may be correct, unless further information is supplied.

    See DstTzInfo.normalize() for more info

    '''
       

