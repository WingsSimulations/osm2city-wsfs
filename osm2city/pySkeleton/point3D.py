#===============================================================================
#   File :      point3D.py
#   Author :    Olivier Teboul, olivier.teboul@ecp.fr
#   Date :      31 july 2008, 14:12
#   Class :     Point3D
#===============================================================================

from math import sqrt

class Point3D:
    """ a 3D point is the 3D version of a point, with 3 coordinates """
    
    def __init__(self, xxx_todo_changeme):
        (x, y, z) = xxx_todo_changeme
        self.x = x
        self.y = y
        self.z = z
    
    def __repr__(self):
        return "Point3D((%f,%f,%f)) " %(self.x, self.y, self.z)
    
    def getData(self):
        return (self.x, self.y, self.z)
    
    def __neg__(self):
        return Point((-self.x, -self.y, -self.z))
    
    def __eq__(self, other):
        return (self-other).norm() < 1e-6
    
    def __sub__(self, other):
        return Point3D((self.x - other.x, self.y - other.y, self.z - other.z))
    
    def __add__(self, other):
        return Point3D((self.x+other.x, self.y+other.y, self.z+other.z))
    
    def __mul__(self, other):
        """ Dot product """
        return self.x*other.x + self.y * other.y + self.z * other.z
    
    def __getitem__(self, i):
        return self.getData()[i]
    
    def copy(self):
        return Point((self.x, self.y, self.z))
    
    def norm(self):
        return sqrt(self.x**2 + self.y**2 + self.z**2)
        
    def scalar_prod(self, alpha):
        self.x *= alpha
        self.y *= alpha
        self.z *= alpha
    
    def cross_prod(self, other):
        return Point3D((self.y*other.z - self.z*other.y,
                        self.z*other.x - self.x*other.z,
                        self.x*other.y - self.y*other.x))
    
    def normalize(self):
        n = self.norm()
        if n:
            self.scalar_prod(1/float(n))
    
    def distance(self, other):
        return (self-other).norm()
    
    def scale(self, poly):
        rsp = Point3D(self.getData())
        rsp.scalar_prod(float(s))
        return rsp
    
    #def display(self,viewer):
        #""" Display the projection on z = 0 """
        #proj = Point((self.x,self.y))
        #proj.display(viewer)
    
