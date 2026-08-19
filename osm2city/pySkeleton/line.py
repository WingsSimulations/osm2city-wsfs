#===============================================================================
#   File :      line.py
#   Author :    Olivier Teboul, olivier.teboul@ecp.fr
#   Date :      23 july 2008, 12:48
#   Class :     Line
#===============================================================================

from math import sqrt
import numpy, numpy.linalg
from . import point

class Line:
    """
    The Line class provides a cartesian representation of lines as the equation:
        ax + by = c = 0
    """

    def __init__(self,a=0.,b=1.,c=0.):
        self.a = a
        self.b = b
        self.c = c
        self.normalise()

    def __repr__(self):
        return "%f %f %f" %(self.a, self.b, self.c)

    def __getitem__(self, i):
        return self.getData()[i]

    def getData(self):
        return [self.a, self.b, self.c]

    def norm(self):
        return sqrt(self.a**2+self.b**2)
        
    def normalise(self):
        n=self.norm()
        self.a *= 1/float(n) 
        self.b *= 1/float(n)
        self.c *= 1/float(n)
        
    def fromVector(self, p1, p2):
        p=(p2-p1).getNormal()
        self.a=p.x
        self.b=p.y
        self.c=-p*p1
        self.normalise()
        
    def distance(self, p):
        return -(self.a*p.x + self.b*p.y+self.c)

    def intersect(self, segment):
        p1=segment[0]
        p2=segment[1]
        t=-1
        a=self.a
        b=self.b
        c=self.c
        q= point.Point((a, b))
        if (p1-p2)*q != 0:
            t=-(c+p2*q)/float((p1-p2)*q)
            p=p1.get_scalar_prod(t)+p2.get_scalar_prod(1-t)
        if (t>=0)and(t<=1):
            return p
        else:
            return False
        
    def intersect_line(self, d):
        """ Intersection of two lines. d is a line. It returns a point"""
        a = numpy.matrix([[self.a, self.b], [d.a, d.b]])
        b = numpy.matrix([[-self.c], [-d.c]])
        try :
            x = numpy.linalg.solve(a, b)
            return point.Point((x.A[0][0], x.A[1][0]))
        except :
            return False

    #def display(self,disp):
        #""" Disp : Display"""

        ##display the line itself
        #if not self.a==0:
            #disp.canvas.create_line(-self.c*disp.size/self.a+disp.offset,0+disp.offset,
                                    #(-self.b*disp.size-self.c*disp.size)/self.a+disp.offset,disp.size+disp.offset,
                                    #width=5,fill='purple')
            
        #elif not self.b==0:
            #disp.canvas.create_line(0+disp.offset,-self.c*disp.size/self.b+disp.offset,
                                    #disp.size+disp.offset,(-self.a*disp.size-self.c*disp.size)/self.b+disp.offset,
                                    #width=5,fill='purple')
            
        #else:
            #pass       
        
        
