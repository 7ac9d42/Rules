{
  rules[NR] = $0
  suffixes[NR] = substr($0, 1, 2) == "+."
  domains[NR] = suffixes[NR] ? substr($0, 3) : $0
}

END {
  for (i = 1; i <= NR; i++) {
    covered = 0
    for (j = 1; j <= NR; j++) {
      if (i == j || !suffixes[j])
        continue

      parent = domains[j]
      child = domains[i]
      if (child == parent ||
          (length(child) > length(parent) &&
           substr(child, length(child) - length(parent), length(parent) + 1) == "." parent)) {
        covered = 1
        break
      }
    }

    if (!covered)
      print rules[i]
  }
}
