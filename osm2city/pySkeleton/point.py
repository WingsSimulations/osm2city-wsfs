#===============================================================================
#   File :      point.py
#   Author :    Olivier Teboul, olivier.teboul@ecp.fr
#   Date :      23 july 2008, 12:48
#   Class :     Point
#===============================================================================

from math import sqrt

class Point:
    """
    2D points or 2D vectors
    This class provides some methods to handle 2D vectors and 2D points :
        * addition of 2 vectors
        * dot product of 2 vectors
        * compute the norm of the vector
        * multiply a vector by a scalar
        * normalize a vector
        * distance between 2 points
        * decide whether or not a point is inside a polygon
        * display a point
    """

    def __init__(self, xxx_todo_changeme):
        (x, y) = xxx_todo_changeme
        self.x      = x
        self.y      = y

    def __repr__(self):
        return "Point((%f,%f)) " %(self.x, self.y)

    def getData(self):
        return (self.x, self.y)

    def __neg__(self):
        return Point((-self.x, -self.y))

    def __eq__(self, other):
        return (self-other).norm()<1e-7
        #return (self.x==other.x and self.y==other.y)

    def __sub__(self, other):
        return Point((self.x - other.x, self.y - other.y))

    def __add__(self, other):
        return Point((self.x+other.x, self.y+other.y))
    
    def __mul__(self, other):
        """ dot product """
        return self.x*other.x + self.y * other.y

    def __getitem__(self, i):
        return self.getData()[i]
    
    def copy(self):
        return Point((self.x, self.y))
    
    def norm(self):
        return sqrt(self.x**2 + self.y**2)

    def getNormal(self):
        a = Point((-self.y, self.x))
        a.normalize()
        return a

    def scalar_prod(self, alpha):
        self.x *= alpha
        self.y *= alpha

    def get_scalar_prod(self, alpha):
        return Point((self.x * alpha, self.y * alpha))

    def cross_prod(self, other):
        return float(self.x*other.y-self.y*other.x)

    def normalize(self):
        n = self.norm()
        if n:
            self.scalar_prod(1/float(n))

    def distance(self, q):
        return (self-q).norm()
    
    def inside(self, poly):
        from . import line
        test=True
        for p in poly:
            q=poly.get_next()
            myLine= line.Line()
            myLine.fromVector(p, q)
            test= test and myLine.distance(self)>=0
        return test

    def scale(self, s):
        rsp = Point(self.getData())
        rsp.scalar_prod(float(s))
        return rsp
    
    #def display(self, disp, color='pink',radius = 3):
        #""" display the point self on the viewer disp, using scale s """
        #disp.canvas.create_oval(self.x-radius,self.y-radius,
                                #self.x+radius,self.y+radius,
                                #fill = color)
                                
