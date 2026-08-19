class SSEvent:
    """ Event that can occur during the straight skeleton algorithm """
    
    def __init__(self, sd):
        self.shrinking_distance = sd

    def __lt__(self, other):
        return self.shrinking_distance < other.shrinking_distance
    
    def __eq__(self, other):
        return abs(self.shrinking_distance - other.shrinking_distance)<1e-6
    
    def isEdgeEvent(self):
        return False
    
    def isVertexEvent(self):
        return False
    
    def isNoEvent(self):
        return False
    
    def isSplitEvent(self):
        return False


class EdgeEvent(SSEvent):
    """ An edge event occurs when an edge shrinks to a point """
    
    def __init__(self, sd, vertex):
        SSEvent.__init__(self, sd)
        self.vertex = vertex
        
    def __repr__(self):
        return "Edge Event :\n" + self.vertex.__repr__() + " - distance : %f\n" %(self.shrinking_distance)
        
    def isEdgeEvent(self):
        return True


class SplitEvent(SSEvent):
    """ A Split event occurs when an edge is splitted into two by a reflex vertex """
    
    def __init__(self, sd, edge, reflex_vertex):
        SSEvent.__init__(self, sd)
        self.splitted_edge = edge
        self.reflex_vertex = reflex_vertex
        
    def isSplitEvent(self):
        return True
    
    def isInEventList(self, liste):
        """ Check if an event belongs to a list """
        result = False
        
        for element in liste:
            if element.isSplitEvent():
                if element.splitted_edge == self.splitted_edge and element.reflex_vertex == self.reflex_vertex:
                    result = True
                    break
                
        return result

    def __repr__(self):
        return "Split Event :\n" + self.splitted_edge.__repr__() + " - " + self.reflex_vertex.__repr__() + " - distance : %f\n" %(self.shrinking_distance)


class VertexEvent(SSEvent):
    """ A vertex event occurs when two or more reflex vertices collide """
    
    def __init__(self, sd, reflexs):
        SSEvent.__init__(self, sd)
        self.reflexs = reflexs
    
    def isVertexEvent(self):
        return True

    
class NoEvent(SSEvent):
    """ When there is no event to occur... """
    
    def __init__(self):
        SSEvent.__init__(self, 1000000000)
    
    def isNoEvent(self):
        return True
    
    def __repr__(self):
        return "No event...\n"
    

# ===============================================================================
if __name__ == '__main__':
    a = SplitEvent(8, None)
    b = SplitEvent(8, None)
    c = EdgeEvent(11, None)
    
    print(a<b)
    print(a<c)