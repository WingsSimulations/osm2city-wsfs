#===============================================================================
#   File :      graph.py
#   Author :    Olivier Teboul olivier.teboul@ecp.fr
#   Date :      05 august 2008, 17:38
#   Class:      Graph
#===============================================================================

from . import point


#===============================================================================
# Node
#===============================================================================
class Node:
    """
    Node of the graph
    3D point + list of neighboring arcs
    """
    
    count = 0
    
    def __init__(self, p):
        self.value      = p

        self.id         = Node.count
        Node.count      = Node.count + 1

        self.neighbors  = []
        self.visited    = False
        
    def __eq__(self, other):
        return self.value == other.value

    def __repr__(self):
        return self.id.__repr__()
            
    def add_neighbor(self, a):
        try :
            return self.neighbors.index(a)
        except:
            self.neighbors.append(a)
            return len(self.neighbors)-1
                
    def minimal_path_to(self, other):
        """
        find the minimal path between two nodes 
        return the path = list of ids
        """
        self.visited = True
        
        distance = 100000000
        path = None
        
        for a in self.neighbors:
            #neighbors are arcs -> get the node
            p = a.get_other_end(self)
            
            if not p.visited:
                if p==other:
                    path = [p]
                    return path
                
                else:
                    #compute the minimal path from here
                    min_path = p.minimal_path_to(other)
                    
                    #if there is a path going from this neighbor to the target
                    if min_path:
                        #compute the length of the path
                        path_length = 0
                        start       = self
                        for q in min_path:
                            path_length += Arc(start, q).distance()
                            start = q
                        
                        #check if this path is minimal
                        if path_length<distance:
                            distance    = path_length
                            path        = [p] + min_path
                    
                        #unvisit the node of this path
                        for q in min_path:
                            q.visited = False
        
        return path


#===============================================================================
# Arc
#===============================================================================
class Arc:
    """
    An arc between two nodes
    """
    
    def __init__(self, p1, p2):
        self.p1 = p1
        self.p2 = p2
        
    def __eq__(self, other):
        """
        Compare two arcs
        As the arcs represent undirected links, arc(p1,p2) = arc(p2,p1)
        """
        return ((self.p1 == other.p1) and (self.p2 == other.p2)) or ((self.p1 == other.p2) and (self.p2 == other.p1))
    
    def distance(self):
        """
        give the length of the arc
        if the arc connect 2D points, it give the euclidian distance between the two end points
        """
        if isinstance(self.p1.value, type(point.Point((0, 0)))):
            return (self.p1.value - self.p2.value).norm()
        else:
            return 1
    
    #def display(self,viewer,color='blue'):
        #"""
        #Display an arc in a viewer, provided that the values of the nodes are 2D points
        #"""
        #try:
            #seg_arc = segment.Segment(self.p1.value,self.p2.value)
            #seg_arc.display(viewer,color)
            
        #except:
            #print 'the vertices of the graph don\'t represent 2D points. Impossible to display the graph on a canvas. Try exportPNG if you want to have a graphViz based representation.'
    
    def __repr__(self):
        return self.p1.__repr__() +" -- "+ self.p2.__repr__()
    
    def get_other_end(self, p):
        if p==self.p1:
            return self.p2
        elif p==self.p2:
            return self.p1
        else:
            print('O_o')


#===============================================================================
# Graph
#===============================================================================
class Graph:
    """
    This class provide tools to build a undirected graph, to manipulate it and
    to find minimal path
    """
    
    def __init__(self, nodes=[], arcs=[]):
        Node.count = 0
        self.nodes = nodes
        self.arcs = arcs
        
    def reset_visit(self):
        for node in self.nodes:
            node.visited = False
    
    def find(self, value):
        """ Find the node of the graph which value is 'value' """
        result = False
        for node in self.nodes:
            if node.value == value:
                result = node
                break
        return result
        
    #===========================================================================
    # Change the topology of the graph
    #===========================================================================
    def add_arc(self, p1, p2):
        """
        @arg p1 : Node
        @arg p2 : Node
        @return : the created arc itself
        """
        
        a = Arc(p1, p2)
        if p1==p2:
            return None
        
        if not a in self.arcs:
            self.arcs.append(a)    
            p1.add_neighbor(a)
            p2.add_neighbor(a)
        
        return a
        
    def add_node(self, p):
        """
        @arg p : the value of the node to be added. The information contained in the node
                 to be created. (point, index, whatever)
        
        @return : the node that had been created, or the one that already
                  existed with the given value p
        """
        
        node_p = Node(p)
        try :
            index = self.nodes.index(node_p)
            Node.count -= 1 #take care, by creating a node, we have increment the count of existing Nodes.
            return self.nodes[index]
        except:
            self.nodes.append(node_p)
            return node_p
        
    def delete_node(self,index=-1):pass
    
    def delete_arc(self,index=-1):pass
    
    #===========================================================================
    # Visualization of the graph
    #===========================================================================
    def exportDOT(self,filename='graph'):
        """ create a dot file """
        
        dotFile = open(filename+'.dot', 'w')
        dotFile.write("graph G {\n")
        for p in self.nodes:
            dotFile.write('\tNode%i [label = "%i"];\n' %(p.id, p.id))
        for a in self.arcs:
            dotFile.write('\tNode%i -- Node%i [label ="%i"];\n' %(a.p1.id, a.p2.id, a.distance()))
        dotFile.write("}\n")
        dotFile.close()
        
#    def _exportPNG(self,filename='graph'):
#        """ Export to png, using graphViz"""
#        self.exportDOT(filename)
#        os.system("dot -Tpng %s.dot -o %s.png" %(filename,filename))
#        os.remove("%s.dot" %(filename))
#        os.system('%s.png' %(filename))
#        
#    def display(self,viewer):
#        """
#        Display the graph in a viewer, provided that the values of the nodes are 2D points
#        """
#        for a in self.arcs:
#            a.display(viewer,color = 'orange')
#            
#        for p in self.nodes:
#            viewer.canvas.create_text(p.value.x + 12, p.value.y +12,
#                                      text="%i" %(p.id),
#                                      fill="DarkOrchid4",font=("Helvectica", "14"))
#        
        
    def __str__(self):
        s  = "arcs %s " % self.arcs
        s += "nodes %s" % self.nodes
        s += " --> " + str([node.value for node in self.nodes])
        return s
#===============================================================================
if __name__ == '__main__':
    g = Graph()
    p0  = g.add_node(0)
    p1  = g.add_node(1)
    p2  = g.add_node(2)
    p3  = g.add_node(3)
    p4  = g.add_node(4)
    p5  = g.add_node(5)
    p6  = g.add_node(6)
    p7  = g.add_node(7)
    p8  = g.add_node(8)
    p9  = g.add_node(9)
    p10 = g.add_node(10)
    p11 = g.add_node(11)
    p12 = g.add_node(12)
    p13 = g.add_node(13)
    p14 = g.add_node(14)
    p15 = g.add_node(15)
    p16 = g.add_node(16)
    p17 = g.add_node(17)
    
    g.add_arc(p0, p1)
    g.add_arc(p0, p2)
    g.add_arc(p0, p3)
    g.add_arc(p2, p4)
    g.add_arc(p2, p5)
    g.add_arc(p3, p11)
    g.add_arc(p3, p9)
    g.add_arc(p3, p17)
    g.add_arc(p17, p8)
    g.add_arc(p9, p10)
    g.add_arc(p10, p14)
    g.add_arc(p4, p7)
    g.add_arc(p7, p6)
    g.add_arc(p5, p6)
    g.add_arc(p6, p8)
    g.add_arc(p11, p12)
    g.add_arc(p12, p13)
    g.add_arc(p13, p17)
    g.add_arc(p13, p15)
    g.add_arc(p15, p16)
    g.add_arc(p16, p8)
        
    g.exportPNG()
    
    print(p0.minimal_path_to(p8))
