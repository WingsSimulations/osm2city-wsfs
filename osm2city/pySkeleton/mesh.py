# ===============================================================================
#   File :      mesh.py
#   Author :    Olivier Teboul, olivier.teboul@ecp.fr
#   Date :      31 july 2008, 14:03
#   Class :     Mesh
# ===============================================================================


class Mesh:
    """
    A mesh is represented by an indexed face structure (IFS):
        * a list of vertices
            -> a vertex is a 3D point
        * a list of faces
            -> a face is a list of indices from the vertices list

    This class provides methods to :
        * create a 3D Mesh
        * save it as a sketchup file
        * save and load (with an internal format)
    """

    def __init__(self, vertices=None, faces=None):
        self.vertices = vertices
        if self.vertices is None:
            self.vertices = list()
        self.faces = faces
        if self.faces is None:
            self.faces = list()
        self.nv = len(self.vertices)
        self.nf = len(self.faces)

    def add_vertex(self, p):
        """
        add a vertex into the list of vertices if the vertex is not already in the list
        @return the index of the vertex in the vertices list
        """
        try:
            return self.vertices.index(p)
        except ValueError:
            self.vertices.append(p)
            self.nv += 1
            return self.nv-1

    def add_face(self, face):
        """ add a face and return the index of the face in the list """
        self.faces.append(face)
        self.nf += 1
        return self.nf-1
