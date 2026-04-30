{
  description = "Reproducible environment for or-tools bisection against SLOTHY";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            cmake
            ninja
            swig
            python3Full
            python3Packages.pip
            python3Packages.setuptools
            python3Packages.virtualenv
            python3Packages.wheel
            git
            perl
            gnumake
            gcc
          ];

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.stdenv.cc.cc.lib}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            echo "or-tools bisection environment ready"
            echo "cmake: $(cmake --version | head -n1)"
            echo "python: $(python3 --version)"
            echo ""
            echo "Usage:"
            echo "  python3 scripts/bisect.py --good v9.7 --bad v9.8"
          '';
        };
      });
}
