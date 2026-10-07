// highlight.js grammar ported from the MOOSE Prism fork (zachmprince/prism).
import type { Language } from "highlight.js";

export default function moose(): Language {
  // case-insensitive helper (hljs can't take per-rule regex flags)
  const ci = (w: string) => w.split("").map((c) => (/[a-z]/i.test(c) ? `[${c.toLowerCase()}${c.toUpperCase()}]` : c)).join("");
  // longest-first so QUAD4 isn't split into QUAD + 4 (the Prism grammar had this bug)
  const alt = (words: string, f: (w: string) => string = ci) =>
    words.split("|").sort((a, b) => b.length - a.length).map(f).join("|");

  const PARSED = "\\w+<<<.*?>>>";

  const BLOCKS =
    "Adaptivity|Bounds|Mesh|MeshDivisions|MeshGenerators|MeshModifiers|Kernels|AuxKernels|ScalarKernels|AuxScalarKernels|Variables|AuxVariables|Materials|FunctorMaterials|Postprocessors|BCs|ICs|Executioner|Executors|Outputs|Problem|Physics|Debug|Preconditioning|UserObjects|Functions|GlobalParams|VectorPostprocessors|Dampers|DiracKernels|DGKernels|Constraints|NodalNormals|CoupledProblems|DeprecatedBlock|MultiApps|Transfers|InterfaceKernels|NodalKernels|Controls|Modules|Positions|Times|FluidProperties|SolidProperties|Closures|Components|ControlLogic|FVBCs|FVKernels|FVInterfaceKernels|Distributions|Likelihood|Samplers|Surrogates|VariableMappings|Reporters|OptimizationReporter|Splits|RayBCs|RayKernels|TimeStepper|TimeSteppers|TimePeriods|Quadrature|Predictor|Indicators|Markers|Periodic|InitialCondition|MortarInterfaces|Partitioner";
  const ORDER = "CONSTANT|FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH";
  const FAMILY =
    "LAGRANGE_VEC|LAGRANGE|MONOMIAL_VEC|MONOMIAL|HERMITE|SCALAR|SIDE_HIERARCHIC|HIERARCHIC|CLOUGH|XYZ|SZABAB|BERNSTEIN|RATIONAL_BERNSTEIN|L2_LAGRANGE|L2_HIERARCHIC";
  const ELEM =
    "EDGE|EDGE2|EDGE3|EDGE4|QUAD|QUAD4|QUAD8|QUAD9|TRI3|TRI6|HEX8|HEX20|HEX27|HEX|TET4|TET10|PRISM6|PRISM15|PRISM18|PYRAMID5|PYRAMID13|PYRAMID14";
  const OUTPUT_ON = "none|initial|linear|nonlinear|timestep_end|timestep_begin|final|failed|custom";
  const EXEC_ON =
    "none|initial|linear|nonlinear|timestep_end|timestep_begin|multiapp_fixed_point_begin|multiapp_fixed_point_end|final|custom|always|forward|adjoint";
  const BUILTINS =
    "abs|acos|acosh|arg|asin|atan|atan2|atanh|cbrt|ceil|conj|cos|cosh|cot|csc|exp|exp2|floor|hypot|if|imag|int|log|log10|log2|max|min|polar|pow|real|sec|sin|sinh|sqrt|tan|tanh|trunc|plog|fparse|units";

  const LB_TYPE = "(?<=\\btype\\s*=\\s*)";
  const listIn = (w: string) => `(?:${alt(w)})(?:\\s+(?:${alt(w)}))*`;

  return {
    name: "MOOSE input",
    aliases: ["i", "moose", "hit", "getpot"],
    disableAutodetect: true,
    contains: [
      { scope: "comment", begin: /(?<!\\)#/, end: /$/ },
      { scope: "keyword", begin: `(?<=[\\[\\/])${PARSED}(?=[\\/\\]])` }, // moose-parsed-syntax
      { scope: "keyword", begin: `(?<=[\\[\\/])(?:${BLOCKS})(?=[\\]\\/])` }, // moose-syntax
      { scope: "title", begin: "(?<=(?:^|\\s)\\[|\\/)\\w+(?=\\]$)" }, // moose-object
      { scope: "function", begin: `${LB_TYPE}${PARSED}` }, // moose-parsed-class
      { scope: "function", begin: `${LB_TYPE}[^\\s]+\\b` }, // moose-class
      { scope: "keyword", begin: "\\btype(?=\\s*=\\s*)" }, // moose-type
      { scope: "attr", begin: `\\b${PARSED}(?=\\s*=\\s*)` }, // moose-parsed-parameter
      { scope: "symbol", begin: `(?<=\\border.*=\\s*)(?:${alt(ORDER)})\\b` }, // moose-order
      { scope: "symbol", begin: `(?<=\\bfamily.*?=\\s*)(?:${alt(FAMILY)})\\b` }, // moose-family
      { scope: "symbol", begin: `(?<=\\belem_type.*=\\s*)(?:${alt(ELEM, (w: string) => w)})\\b` }, // moose-elem-type
      { scope: "symbol", begin: `(?<=\\boutput_on.*=\\s*['"])${listIn(OUTPUT_ON)}(?=['"])` },
      { scope: "symbol", begin: `(?<=\\bexecute_on.*=\\s*['"])${listIn(EXEC_ON)}(?=['"])` },
      { scope: "attr", begin: "\\b\\w+(?=\\s*=\\s*)" }, // moose-parameter
      { scope: "built_in", begin: `\\b(?:${BUILTINS})\\b` },
      {
        scope: "number",
        begin:
          /\b0(?:[bB](?:_?[01])+|[oO](?:_?[0-7])+|[xX](?:_?[a-fA-F0-9])+)\b|(?:\b\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\B\.\d+(?:_\d+)*)(?:[eE][+-]?\d+(?:_\d+)*)?[jJ]?(?!\w)/,
      },
      { scope: "literal", begin: `\\b(?:${alt("false|true")})\\b` },
      { scope: "operator", begin: /[+*/^%-]/, relevance: 0 },
      { scope: "punctuation", begin: /['"]/, relevance: 0 },
      { scope: "property", begin: /\w+\b(?!\s*=)/, relevance: 0 },
    ],
  };
}
