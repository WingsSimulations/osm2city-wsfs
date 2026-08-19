#===============================================================================
#   File :      polygon.py
#   Author :    Olivier Teboul olivier.teboul@ecp.fr
#   Date :      23 july 2008, 12:46
#   Class:      Polygon
#===============================================================================

from .point import Point
from . import point3D
#import display
from . import segment
from . import sector
from . import events
import copy
import math
#import rainbow
from . import mesh
from . import graph

"""
!!!! Known bugs !!!!!
* zero speed
* simultaneous vertex events
"""

class Polygon :
    """
    The Polygon class provides methods to :
        * create a polygon made of vertices, and weighted edges
        * handle polygon with multiple connected components
        * move a vertex of the polygon
        * collapse an edge of the polygon, so that it become a single point
        * split and edge into 2 by collision of a vertex
    """
    
    def __init__(self,vertices=[],edges=[],weights=[]):
        """
        the vertices are given as a list of 2_tuples
        the edges are given as a list of 2 tuples which are the indices of the vertices
        the weigts is a list of float
        """
                
        #initialize the vertices
        self.vertices   = list(map(Point, vertices))
        self.n          = len(self.vertices) #self.n is the number of vertices and also the number of edges, if all the vertices declared are used
        
        #process the edges list to make it consistent with the vertices
        if edges == []: #if no edge have been declared, the vertices are supposed to be given in the good order
            edges = [(i, (i+1)%(self.n)) for i in range(self.n)]
            
        self.edge_indices = edges
        
        if len(weights) > self.n:
            weights = weights[:self.n]
        elif len(weights) < self.n:
            weights += [1 for i in range(self.n-len(weights))]
            
        self.n = len(edges)
        
        #build the edge list
        self.edges = []
        for i in range(self.n):
            curr_indices    = edges[i]
            curr_edge       = segment.Segment(self.vertices[curr_indices[0]],
                                              self.vertices[curr_indices[1]],
                                              weights[i])
            self.edges.append(curr_edge)
        
        #compute the sectors (there are as many sectors as the number of edges, and so as the number of used vertices)
        self.get_sectors()
            
        #track the vertices of the polygon
        self.init_tracking()
        
        
    def init_tracking(self):
        #Track the original vertices of the polygon
        #use an array of indices : track[i] give the index of the vertex linked to vertices[i]
        self.track = list(range(len(self.vertices)))
        
        #follow the differents events in the life of a point
        self.lives = [[copy.deepcopy(p)] for p in self.vertices]
        

    #===========================================================================
    # Load and save a Polygon
    #===========================================================================
    def save(self, filename):
        #open a file
        f = open(filename, 'w')
        
        #save the vertices
        f.write("%i\n" %(len(self.vertices)))
        for p in self.vertices:
            f.write("%f %f\n" %(p.x, p.y))
        
        #save the edges
        f.write("%i\n" %(len(self.edges)))
        for i in range(self.n):
            f.write("%i %i %f\n" %(self.edge_indices[i][0], self.edge_indices[i][1], self.edges[i].w))
            
        f.close()
        
    def load(self, filename):
        f = open(filename, 'r')
        
        #vertices
        nv      = int(f.readline())
        v       = []
        for i in range(nv):
            line = list(map(float, f.readline().split()))
            v.append( (line[0], line[1]) )
        
        #edges
        ne      = int(f.readline())
        e       = []
        w       = []
        for i in range(ne):
            line = list(map(float, f.readline().split()))
            e.append( ( int(line[0]), int(line[1]) ) )
            w.append(line[2])
        
        f.close()
        self.__init__(v, e, w)
        
    def clone(self):
        """
        Return a copy of the polygon
        """
        v2  = [x.getData() for x in self.vertices]
        e2  = self.edge_indices
        w2  = [x.w for x in self.edges]
        
        return Polygon(v2, e2, w2)
            
        
    #===========================================================================
    # Representation of the polygon
    #===========================================================================
    def __repr__(self):
        s = 'Vertices :\n'
        for p in self.vertices:
            s+="\t"+p.__repr__() +"\n"
            
        s+= "\n%i Edges : \n" %(self.n)
        for e in self.edges:
            s+= "\t" + e.__repr__() + "\n"
            
        s+= "\nEdges indices :\n"
        for ind in self.edge_indices:
            s+= "\t %i-%i\n" %(ind[0], ind[1])
            
        return s
    
#    def display(self,viewer):
#        #find the min and max of speed in the polygon
#        min_speed = min(map(lambda x:x.w,self.edges))
#        max_speed = max(map(lambda x:x.w,self.edges))
#            
#        for i in range(self.n):
#            edge    = self.edges[i]
#            if max_speed == min_speed:
#                c = 'black'
#            else :
#                c = rainbow.Rainbow().get_hexa_color(float(edge.w-min_speed)/float(max_speed-min_speed))
#            edge.display(viewer,color=c,w=4)
#            
#            if viewer.show_info:
#                viewer.canvas.create_text(0.5*(edge.pI.x+edge.pF.x),
#                                          0.5*(edge.pI.y+edge.pF.y),
#                                          text="%i" %(i),
#                                          fill="purple",font=("Helvectica", "16"))
        
    #===========================================================================
    # Get information on the polygon
    #===========================================================================     
    def getNext(self, edge_index):
        """
        return the index of the next edge
        The adjacent edge is not necessarily the edge 'edge_index+1'
        """
        next_index = 0
        toBeMatched = self.edge_indices[edge_index][1]
        
        for k in range(self.n):
            curr_edge = self.edge_indices[k]
            if curr_edge[0] == toBeMatched:
                next_index = k
                break
            
        return next_index

    def getLast(self, edge_index):
        """
        return the index of the last edge, the one that ends the same way
        the edge 'edge_index' starts
        """
        last_index = 0
        toBeMatched = self.edge_indices[edge_index][0]
        
        for k in range(self.n):
            curr_edge = self.edge_indices[k]
            if curr_edge[1] == toBeMatched:
                last_index = k
                break
        
        return last_index
    
    def get_sector(self, edge_index):
        """ compute the sector that corresponds to edge number 'edge_index' """
        last_index      = self.getLast(edge_index)
        next_index      = self.getNext(edge_index)
        
        last_edge       = self.edges[last_index]
        current_edge    = self.edges[edge_index]
        next_edge       = self.edges[next_index]
        
        reflex1         = False
        reflex2         = False
        
        h1              = last_edge.bisector_with(current_edge)
        orientation1    = last_edge.u.cross_prod(current_edge.u)>0
        if not orientation1 :
            h1.revert()
            reflex1     = True
            
        h2              = current_edge.bisector_with(next_edge)
        orientation2    = current_edge.u.cross_prod(next_edge.u)>0
        if not orientation2:
            h2.revert()
            reflex2     = True
    
        return sector.Sector(h1, h2, current_edge, reflex1, reflex2)
    
    def get_sectors(self):
        #recompute the sectors and their edge events
        self.sectors = [self.get_sector(i) for i in range(self.n)]
        
        #take the split events into account
        self.update_split_event()
        
    def is_reflex_adjacent(self, sec1, sec2):
        """ sometimes two sectors are not adjacent, but the reflex vertex of one, belongs to
            an edge adjacent to the second one...
        """
        test1 = False
        test2 = False
        
        if sec1.reflex1:
            ir1 = self.vertices.index(sec1.edge.pI)
            for (i, j) in self.edge_indices:
                if j==ir1:
                    other_end = i
                    break
            other_edge_reflex_1 = self.edge_indices.index((other_end, ir1))
            test1 = self.sectors[other_edge_reflex_1].is_adjacent_to(sec2)
            
        if sec1.reflex2:
            ir2 = self.vertices.index(sec1.edge.pF)
            for (i, j) in self.edge_indices:
                if i==ir2:
                    other_end = j
                    break
            other_edge_reflex_2 = self.edge_indices.index((ir2, other_end))
            test2 = self.sectors[other_edge_reflex_2].is_adjacent_to(sec2)
            
        return test1 or test2
    
    #===========================================================================
    # Basic modification of the polygon
    #===========================================================================
    def delete_edge(self, i):
        """
            Delete the edge i, both the indices representation and the points representation
            Do not delete the vertices associated to the ends of the edge
        """
        del self.edges[i]
        del self.edge_indices[i]
        self.n -= 1
        
    def add_edge(self,i1,i2,w=1):
        """
            Add an edge between to existing vertices of the polygon.
            w is the weight of the edge (1 by default)
        """
        self.edge_indices.append((i1, i2))
        self.edges.append(segment.Segment(self.vertices[i1], self.vertices[i2], w))
        self.n += 1
        
        
    def move(self, point_index, new_location):
        """
        Move a point with index 'point_index' to the location of the point 'new_location
        This method modifies both the list of vertices but also the list of edges
        """
        self.vertices[point_index].x = new_location.x
        self.vertices[point_index].y = new_location.y
    
    def collapse_edge(self, edge_index, p):
        """
        When an edge become a single point 'p', we delete the edge from the set of edges
        and connect the p correctly
        """
        #move the first point of the edge 'edge_index' to the location 'p'
        ip1 = self.edge_indices[edge_index][0]
        ip2 = self.edge_indices[edge_index][1]    
        
        #not in the test : must be done!!!
        self.move(ip1, p)
        
        self.move(ip2, p)
        self.track[ip2] = ip1
        self.lives[ip1].append(copy.deepcopy(p))
        
        #update the links
        next = self.getNext(edge_index)
        last = self.getLast(edge_index)
        self.edge_indices[next] = (ip1, self.edge_indices[next][1])
        self.edges[next].pI = self.edges[last].pF
        
        #delete the edge in the list and in the index list
        self.delete_edge(edge_index)
        
    def split_edge(self, split_vertex_index, splitted_edge_index):
        """ a vertex enters an edge and split it into 2 """
        
        #duplicate the vertex that split the edge into 2
        split_vertex    = self.vertices[split_vertex_index]
        clone_vertex    = split_vertex.copy()
        self.vertices.append(clone_vertex)
        clone_index     = len(self.vertices)-1
        
        #update tracks
        self.track.append(len(self.vertices)-1)
        self.lives.append([copy.deepcopy(self.vertices[-1])])
        self.lives[split_vertex_index].append(copy.deepcopy(split_vertex))
        
        #get the indices of the ends of the splitted edge
        i1              = self.edge_indices[splitted_edge_index][0]
        i2              = self.edge_indices[splitted_edge_index][1]
        w               = self.edges[splitted_edge_index].w
                
        #modify the edge which ends by the splitting_point
        toBeModified = 0
        for k in range(len(self.edge_indices)):
            if  self.edge_indices[k][1] == split_vertex_index:
                toBeModified = k
                break
        self.edges[toBeModified].pF = self.vertices[clone_index]
        self.edge_indices[toBeModified] = (self.edge_indices[toBeModified][0], clone_index)

        
        #add 2 edges instead of the splited one
        self.add_edge(i1, split_vertex_index, w)
        self.add_edge(clone_index, i2, w)
    
        #remove the edge that has been splitted.
        self.delete_edge(splitted_edge_index)

        #update the number of edges
        self.n = len(self.edges)
        
    def fusion_points(self, ps, new_point):
        """
        ps is a list of point indices
        modify the topology of the polygon so that all the points of the list end at new_point
        """
        
        #move the point to the location
        for pi in ps:
            self.move(pi, new_point)
            
        #take each point i to collide:
        # it belongs to 2 edges : i - a and b-i
        #keep i-a, and replace c - (i+1) par c-i, etc...
        for i in range(len(ps)):
            curr = ps[i]
            next = ps[(i+1)%len(ps)]
            
            for e in range(len(self.edge_indices)):
                (a, b) = self.edge_indices[e]
                if b == next:
                    self.add_edge(a, curr, self.edges[e].w)
                    self.delete_edge(e)
                    break
        
        self.n = len(self.edges)
    
    def blind_shrink(self, d):
        """
        Shrink the edges of the polygon according to their weight (speed)
        without paying attention to the event that might occur
        """
        for i in range(self.n):
            ip1 = self.edge_indices[i][0]
            ip2 = self.edge_indices[i][1]
            p1  = self.vertices[ip1]
            p2  = self.vertices[ip2]

            new_p1 = self.sectors[i].move_first_point(float(d))
            self.move(ip1, new_p1)
        
    #===========================================================================
    # Find some special event
    #===========================================================================
    def update_split_event(self):
        """
        At construction time, the sectors have no clue about the other sector
        So the event associated to the sector is either a no Event, or a EdgeEvent
        This method enable to update the event field of the reflex sector, so that
        they become aware of the other sector
        """
        for sec1 in self.sectors:
            for sec2 in self.sectors:
                #test if it is worth computing the split event between the two sectors....
                test1 = not sec1.is_adjacent_to(sec2)
                test2 = not (sec1 == sec2)
                test3 = sec1.reflex()
                test4 = not self.is_reflex_adjacent(sec1, sec2)
                
                if test1 and test2 and test3 and test4:
                    sec1.get_split_event(sec2)
                    
                    
    def update_vertex_event(self):
        """
        Check if a vertex event could occur. This is the kind of silly event
        that can mess up everything if it occurs
        """
        for sec1 in self.sectors:
            for sec2 in self.sectors:
                test1 = sec1.reflex()
                test2 = sec2.reflex()
                test3 = not (sec1 == sec2)
                test4 = self.is_reflex_adjacent(sec1, sec2)
                test5 = self.is_reflex_adjacent(sec2, sec1)
                
                sec1.get_vertex_event(sec2)

    def first_event(self):
        """
        compute the first event that is going to happen and to which edge it happens...
        take care of multiple events -> return a list??"""
        self.get_sectors()
        first_event = events.NoEvent()
        event_list  = [first_event]
        index = -1
        
        for i in range(self.n):
            sec = self.sectors[i]
            if sec.event < first_event:
                first_event = sec.event
                index = i
                event_list = [first_event]
                
            elif sec.event == first_event:
                if (sec.event.isSplitEvent() and not sec.event.isInEventList(event_list)) or sec.event.isEdgeEvent():
                    event_list.append(sec.event)
                
            #if sec.event == first_event and sec.event.isSplitEvent():
            #    first_event = sec.event
            #    index = i
            #elif sec.event == first_event:
            #    first_event = sec.event
            #    index = i
            #elif sec.event<first_event:
            #    first_event = sec.event
            #    index = i
            
        return event_list, index #first_event,index
    
    def first_split_event(self):
        """ compute the first split event that is going to happen and to which edge it happens..."""
        self.get_sectors()
        first_event = events.NoEvent()
        
        for i in range(self.n):
            sec = self.sectors[i]
            if sec.event < first_event and sec.event.isSplitEvent():
                first_event = sec.event
                index = i
        
        return first_event
    
    #===========================================================================
    # deal with degenerated case
    #===========================================================================
    def clean_edges(self):
        goOn = False
        
        for i in range(len(self.edges)):
            if self.edges[i].is_degenerated():
                self.collapse_edge(i, self.edges[i].pI)
                goOn = True
                break
        
        if goOn:
            self.clean_edges()
            
    def clean_components(self):
        goOn = False
        
        for i in range(len(self.edge_indices)):
            (a, b) = self.edge_indices[i]
            if self.edge_indices[self.getNext(i)][1]==a:
                j = self.edge_indices.index((b, a))
                self.delete_edge(j)
                self.delete_edge(i)
                self.lives[a].append(self.vertices[b].copy())
                goOn = True
                break
        if goOn:
            self.clean_components()
        
    def clean(self):
        """ erase the edges of the polygon when both ends are at the same location """
        self.clean_edges()
        self.clean_components()
            
    
    #===========================================================================
    # Main function : Shrink to get a straigth skeleton
    #===========================================================================
    def shrink(self, d):
        """
        Shrink the edges of the polygon of distance d, taking into account
        the possible event that can occurs: edge event or split event
        """
        #get the first event:
        self.clean()
        el, index = self.first_event()
        
        #first event = first split event if it exists
        fe = el[0]
        for e in el:
            if e.isSplitEvent():
                fe = e
                break
                    
        while fe.shrinking_distance<=d:            
            #start by shrinking the polygon using the event distance
            self.blind_shrink(fe.shrinking_distance)
            
            #case edge event
            if fe.isEdgeEvent():
                self.collapse_edge(index, self.edges[index].pI)
            
            #case split event
            elif fe.isSplitEvent():
                iv = self.vertices.index(fe.reflex_vertex)
                ie = self.edges.index(fe.splitted_edge)
                self.split_edge(iv, ie)
                
            #case vertex event
            elif fe.isVertexEvent():
                pass
                
            #clean the polygon by erasing other simultaneous edge events, and degenerated configurations
            self.clean()
    
            #update (while loop)
            d -= fe.shrinking_distance
            el, index = self.first_event()        
            #first event = first split event
            fe = el[0]
            for e in el:
                if e.isSplitEvent():
                    fe = e
                    break
            
        #finish the shrink
        if self.n>2:
            self.blind_shrink(d)
            
    
    def raise_loft(self, alpha, h):
        """
        Create the links to build a roofs : with height h, and angle alpha
        we stop before a split event occurs
        """
        
        #initialize the mesh
        self.init_tracking()
        roof    = copy.deepcopy(self)
        
        #compute d1 : it should be smaller than the fisrt shrink event
        max_d   = self.first_split_event().shrinking_distance
        d       = h/math.tan(alpha)
        if d>max_d:
            d=max_d

        #shrink self
        self.shrink(d)
        for i in range(len(roof.vertices)):
            self.lives[i].append(self.vertices[i])
        for edge in self.edges:
            roof.edges.append(segment.Segment(edge.pI, edge.pF, edge.w))
        
        #connect the old points, with the new ones        
        for i in range(len(self.lives)):
            roof.edges.append(segment.Segment(self.lives[i][0], self.lives[self.track[i]][-1]))
            
        #update some parameters
        roof.n = len(roof.edges)
        
        return roof
    
    def straight_skeleton(self):
        """
        Compute the straight skeleton of the polygon as a tree (graph) where :
            * the leaves are the original vertices of the polygon
            * the internal nodes correspond to events (edge or split)
        """
        
        #create a skeleton and make sure it's empty
        skeleton        = graph.Graph()
        skeleton.nodes  = []
        skeleton.arcs   = []
        
        #initialize the computation
        self.init_tracking()
        for p in self.vertices:
            skeleton.add_node(copy.deepcopy(p))
        
        #shrink to the end
        self.shrink(10000)
        
        #add the last points to the lives:
        for i in range(len(self.vertices)):
            self.lives[i].append(self.vertices[i])
            
        #build the arcs in this path
        for i in range(len(self.lives)):
            for j in range(len(self.lives[i])-1):
                p1 = skeleton.add_node(self.lives[i][j])
                p2 = skeleton.add_node(self.lives[i][j+1])
                skeleton.add_arc(p1, p2)
        
        return skeleton
    

    def straight_skeleton_faces(self):
        """
        compute all the faces of the straight_skeleton of the polygon
        """
        clone       = self.clone()
        skeleton    = clone.straight_skeleton()
        
#        skeleton.exportPNG()
        
        faces = []
        for i in range(len(self.edges)):
            face = self.straight_skeleton_get_face(skeleton, i)
            faces.append(face)
        return faces
    
    def straight_skeleton_get_face(self, skeleton, i):
        """
        Compute the face 'i' of the straight skeleton
        """        
        source = None
        target = None
        for node in skeleton.nodes:
            if node.value == self.edges[i].pI:
                source = node
                break
        for node in skeleton.nodes:
            if node.value == self.edges[i].pF:
                target = node
                break
            
        skeleton.reset_visit()
        path = source.minimal_path_to(target)
        face = [source] + path
        
        face2D = []
        for node in face:
            face2D.append(node.value)
                
        return face2D
    
    def roof_face_3D(self, skeleton, msh, i, angle):
        """
        Compute the 3D face 'i' of the roof, based on the straight_skeleton computation
            @arg i          : the number og the face. There are as many faces on the roofs, 
                              as edges on the polygon
            @arg msh        : the mesh 'under construction'
            @arg skeleton   : a graph (computed using straight skeleton)
            @arg angle      : the angle of the roof
        """
        edge    = self.edges[i]
        
        #get target node
        source  = None
        for node in skeleton.nodes:
            if node.value == edge.pI:
                source = node
                break
            
        #get source node
        target  = None
        for node in skeleton.nodes:
            if node.value == edge.pF:
                target = node
                break
    
        #compute the path of nodes                    
        skeleton.reset_visit()
        path = source.minimal_path_to(target)
        face = [source] + path
        
        #turn it into 3D 
        face3D      = []
        tan_angle   = math.tan(angle)
        for node in face:            
            current_point   = node.value
            d               = edge.weighted_distance_to(current_point)
            index           = msh.add_vertex(point3D.Point3D((node.value.x, node.value.y, d * tan_angle)))
            face3D.append(index)
                
        msh.add_face(face3D)
            
    
    def roof_3D(self, angle):
        """ Build a 3D straight skeleton of the roof """
        
        clone               = self.clone()
        skeleton            = clone.straight_skeleton()
        roof_mesh           = mesh.Mesh()
        roof_mesh.vertices  = []
        roof_mesh.faces     = []
        
        #skeleton.exportPNG()
        
        for i in range(len(self.edges)):
            self.roof_face_3D(skeleton, roof_mesh, i, angle)
        
        return roof_mesh

#===============================================================================
# main tests for polygons
#===============================================================================
if __name__ == '__main__':
    #define a polygon 1
    v = [(0, 0), (0, 0.2), (1, 0.2), (1.5, 1.5), (1.5, -0.5), (1, 0)]
    s = 300
    v = [(x[0]*s+100, 500-x[1]*s) for x in v]
    
    #define a second one
    v2 = [(0, 2), (0, 5), (8, 5), (8, 2), (5, 2), (6, 0), (2, 0), (3, 2)]
    s2 = 60
    v2 = [(x[0]*s2+100, 500-x[1]*s2) for x in v2]
    
    #test fusion
    v3 = [(5, 7), (10, 8), (10, 5), (13, 5), (13, 2), (9, 2), (9, 0), (6, 0), (6, 2), (4, 0), (1, 1), (3, 3), (0, 4), (4, 5)]
    s3 = 40
    v3 = [(x[0]*s3+100, 500-x[1]*s3) for x in v3]
    
    p = Polygon(v2)
    #p.fusion_points([3,8,13],Point((7*s3+100,500-4*s3)))
    #p.clean()
    #p.get_sectors()

        
#    viewer = display.Viewer()
#    viewer.polygon = p
#    viewer.display()
#    viewer.mainloop()
#    

    
    
    
    
    
    