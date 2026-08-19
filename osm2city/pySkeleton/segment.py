#===============================================================================
#   File :      segment.py
#   Author :    Olivier Teboul, olivier.teboul@ecp.fr
#   Date :      23 july 2008, 13:20
#   Class :     Segment, ParallelSegmentError
#===============================================================================

from .line import Line
from . import half_line


#import display

class SegmentError(Exception):pass
class ParallelSegmentError(SegmentError):pass
class OppositeSegmentError(SegmentError):pass

class Segment:
    """
    A segment is made of two point and a weight, or a speed
    This class provides tools to :
        * define a weighted segment
        * compute the distance between a point and a segment
        * compute the bisector half line of two segments
    """
        
    def __init__(self,pI,pF,w=1.0):
        self.pI = pI
        self.pF = pF
        self.w  = w
        self.u  = self.pF - self.pI
        self.u.normalize()
        
    def __repr__(self):
        return "Segment : " + self.pI.__repr__() + "- " + self.pF.__repr__() + "  weight : %f" %(self.w)
    
    def __eq__(self, other):
        return ((self.pI==other.pI and self.pF==other.pF) or (self.pI==other.pF and self.pF==other.pI))
    
    def getData(self):
        return(self.pI, self.pF)
        
    def __getitem__(self, i):
        return self.getData()[i]
    
    def distance_to(self, p):
        """ compute the normal distance between p and the segment """
        u = self.pF-self.pI
        u.normalize()
        v = p - self.pI
        
        d = v - u.get_scalar_prod(v*u)
        return d.norm()
    
    def weighted_distance_to(self, p):
        """
        compute the distance from a point to the segment, taking the weight (or speed)
        of the segment into account
        """
        return self.distance_to(p)/float(self.w)
    
    def is_degenerated(self):
        """ decide if a segment is reduced to a single point """
        return (self.pI - self.pF).norm()<1e-6
    
    def bisector_with(self, other):
        """ compute the bisector of two segments """
        
        bisector = None

        try :
            #find the intersection point of the two lines that carry the segments
            inter = None
            if self.pI == other.pI or self.pI == other.pF:
                inter = self.pI
            elif self.pF == other.pI or self.pF == other.pF:
                inter = self.pF
            else:
                l1 = Line()
                l1.fromVector(self.pI, self.pF)
                l2 = Line()
                l2.fromVector(other.pI, other.pF)
            
                inter = l1.intersect_line(l2)
                if not inter : raise ParallelSegmentError
            
            #compute the bisector, according to the weights
            #!!! @todo : Take the case of zero speed into account !!!
            u1 = (self.pI+self.pF).scale(0.5)- inter
            if u1.norm() == 0:
                u1 = self.pI - inter
            u2 = (other.pI+other.pF).scale(0.5) - inter
            if u2.norm() == 0:
                u2 = other.pI - inter
            u1.normalize()
            u1.scalar_prod(1./float(self.w))
            u2.normalize()
            u2.scalar_prod(1./float(other.w))
            bisector = half_line.Hline(u1 + u2, inter)
        
        except(ParallelSegmentError) :
            d = 0.5*self.distance_to(other.pI)
            inter = self.pI + self.u.getNormal().scale(d)
            inter = inter - self.u.scale(10000000)
            bisector = half_line.Hline(self.u, inter)
            
        except(OppositeSegmentError):
            bisector = half_line.Hline(self.u.getNormal(), self.pI)
            
        return bisector
    
    #def display(self,disp,color='blue',w=3):
        #""" display the segment on a Tkinter canvas """
               
        ##display the half line itself
        #disp.canvas.create_line(self.pI.x, self.pI.y, self.pF.x, self.pF.y, fill=color,width=w)
        
        ##display both ends
        #self.pI.display(disp)
        #self.pF.display(disp)
    
#===============================================================================
#if __name__ == '__main__':
    #s1 = Segment(point.Point((400,300)),point.Point((100,300)),1)
    #s2 = Segment(point.Point((100,100)),point.Point((400,100)),1)
    
    #h = s1.bisector_with(s2)
    #print h
    
    #viewer = display.Viewer();
    #h.display(viewer)
    #s1.display(viewer,color='red')
    #s2.display(viewer)
    #viewer.mainloop()
    
