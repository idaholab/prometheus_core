# Mesh test fixtures

`square.e`: a 2×2 QUAD4 mesh (9 nodes, 4 elements), Exodus II.

- Source: [MOOSE](https://github.com/idaholab/moose), `examples/ex01_inputfile/square.e`, unchanged since commit `0895867035ea3420a4a8904afdb348aecd4d09ad`.
- License: GNU LGPL 2.1, as part of MOOSE. It is used here unmodified, as test data only. It is not part of the shipped backend.
- Why it's here: VTK's `vtkExodusIIWriter` crashes when asked to write a mesh, so a test can't generate a valid Exodus file at run time.
