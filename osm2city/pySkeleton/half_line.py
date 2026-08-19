#===============================================================================
#   File :      half_line.py
#   Author :    Olivier Teboul olivier.teboul@ecp.fr
#   Date :      23 july 2008, 12:56
#   Class:      Hline
#===============================================================================

from .point import Point
#import display
import numpy, numpy.linalg


class Hline:
    """
    The Hline class provides a representation of half line, and some methods to:
        * display a half line
        * intersect a half line with another half line, or with a segment
    """
    
    def __init__(self, direction, p):
        self.d = direction
        self.d.normalize()
        self.p = p
        self.n = self.d.getNormal()
        
    def __repr__(self):
        return "* Point : " + self.p.__repr__() + " --> direction : " + self.d.__repr__()
        
    def revert(self):
        """ reverse the direction of the half line"""
        self.d = -self.d
        
#    def display(self,disp):
#        p2 = self.p + self.d.scale(50000)
#        p3 = self.p + self.n.scale(20)
#        
#        #display the point
#        self.p.display(disp,color = 'green', radius = 6)
#        
#        #display the half line itself
#        disp.canvas.create_line(self.p.x, self.p.y, p2.x, p2.y, fill="orange",width=3)
#        
#        #display the normal (orientation)
#        disp.canvas.create_line(self.p.x,self.p.y,p3.x,p3.y,fill="black",width=2)
    
    def side(self, p):
        q = p-self.p
        return self.d.cross_prod(q)>= 0
    
    def getPoint(self, alpha):
        """
        return the point p+a*d, belonging to the half line
        """
        return self.p + self.d.scale(alpha)
    
    def intersect(self, other):
        """intersection of two half line"""
        result = None
        
        #linear system
        a = numpy.matrix([[self.d.x, -other.d.x], [self.d.y, -other.d.y]])
        b = numpy.matrix([[-self.p.x+other.p.x], [-self.p.y+other.p.y]])
        
        try :
            x = numpy.linalg.solve(a, b)
            lambda1 = x.A[0][0]
            lambda2 = x.A[1][0]
            if lambda1 > 0 and lambda2 > 0:
                result = self.getPoint(lambda1)
        except :
            pass
        
        return result

    def intersect_segment(self, seg):
        """ intersection of the half line with the segment """
        result = None
        
        #build the linear system
        a = numpy.matrix([[self.d.x, seg.pF.x-seg.pI.x], [self.d.y, seg.pF.y-seg.pI.y]])
        b = numpy.matrix([[seg.pF.x-self.p.x], [seg.pF.y-self.p.y]])
            
        #try to solve it
        try:
            x = numpy.linalg.solve(a, b)
            alpha = x.A[0][0]  #parameter of the half line
            beta  = x.A[1][0]  #parameter on the segment
            
            #check if the solution is in the segment and in the half line
            if alpha>0 and 0<beta<1:
                result =  self.getPoint(alpha)
        
        except:
            pass
        
        return result
