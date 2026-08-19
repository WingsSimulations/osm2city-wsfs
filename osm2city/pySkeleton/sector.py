#===============================================================================
#   File :      sector.py
#   Author :    Olivier Teboul, olivier.teboul@ecp.fr
#   Date :      23 july 2008, 13:02
#   Classes :   Sector, ParallelLinesError
#===============================================================================

import math
from . import half_line
#import display
from . import events


class Sector:
    """
    A sector of an edge from a polygon is the space where the edge can move in the polygon, going parallel to it's original location,
    and not intersecting with its neighbors. It can be a triangle, or more generally, it's defined by the edge itself, and to bisector
    half lines.
    This class provides methods to :
        * define a sector
        * decide whether or not two sectors have an intersection
        * decide whether or not a sector has a reflex vertex
        * compute the maximum distance the edge of the sector can move inwards relatively to another sector
        * forecast what will be the first conflict to happen to the edge of the sector relatively to another sector: edge event or split event or nothing
        * display the sector
    """
    
    def __init__(self,h1,h2,edge, reflex1 = False, reflex2 = False):
        self.h1         = h1
        self.h2         = h2
        self.edge       = edge
        self.reflex1    = reflex1
        self.reflex2    = reflex2
        self.event      = self.get_edge_event()
        
    def reflex(self):
        return self.reflex1 or self.reflex2
    
    def contains(self, p):
        """ decide whether or not a point 'p' is inside a the sector """
        return (not self.h1.side(p)) and self.h2.side(p) and half_line.Hline(self.edge.u, self.edge.pI).side(p)
    
    def is_adjacent_to(self, other):
        """ decide if the two sectors are adjacent """
        return self.edge.pI == other.edge.pF or self.edge.pF == other.edge.pI
            
    def get_edge_event(self):
        """ compute the freedom of the edge. Can an edge event append to this edge ? """
        
        free    = events.NoEvent()
        top     = self.h1.intersect(self.h2)
        if top:
            free = events.EdgeEvent(self.edge.weighted_distance_to(top), top)
        
        return free
    
    def get_split_event(self, other):
        """
        update the event field by checking if a split event is possible between 'self' and 'other'...
        
        the compatibility between the sectors must have been checked before calling
        """
        
        free    = events.NoEvent()
            
        bisec   = self.edge.bisector_with(other.edge)
        p1      = bisec.intersect(self.h1)
        p2      = bisec.intersect(self.h2)    
        
        candidates = []
        if self.reflex1 and p1 and other.contains(p1):
            candidates.append(events.SplitEvent(self.edge.weighted_distance_to(p1), other.edge, self.h1.p))
        if self.reflex2 and p2 and other.contains(p2):
            candidates.append(events.SplitEvent(self.edge.weighted_distance_to(p2), other.edge, self.h2.p))
                     
        #now we have a list of split events (possibly empty), take the one with minimal distance
        for ev in candidates:
            if ev < free:
                free = ev
        
        if free < self.event:
            self.event = free
            
    def get_vertex_event(self, other):
        """"
        update the event field by checking if a vertex event is possible between 'self' and 'other'
        The configuration is supposed to have been checked before, so that we know that computing a reflex event makes sense
        """
        #find the possible conflicts
        
        #compute the reflex events between them
        
        #keep the minimum

    def move_first_point(self, d):
        """ move the first point along the first half line with respect to its speed """
        cosAlpha = self.edge.u*self.h1.d
        alpha = 0.0000001  # if cosAlpha outside allowed range, then assume max value (= 1) and therefore acos(1) = 0
        if -1. <= cosAlpha <= 1.:
            alpha = math.acos(cosAlpha)
        s = d*float(self.edge.w)/math.sin(alpha)
        return self.h1.getPoint(s)        
