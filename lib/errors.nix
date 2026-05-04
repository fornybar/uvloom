{ }:

{
  show = value: builtins.toJSON value;

  fail = where: message: throw "uvloom.${where}: ${message}";
}
