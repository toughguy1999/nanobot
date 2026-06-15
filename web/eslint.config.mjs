import { FlatCompat } from "@eslint/eslintrc";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals.js";
import nextTypescript from "eslint-config-next/typescript.js";

const compat = new FlatCompat();

const eslintConfig = [
  {
    ignores: [".next/**", "node_modules/**", "dist/**", "out/**"]
  },
  ...compat.config(nextCoreWebVitals),
  ...compat.config(nextTypescript)
];

export default eslintConfig;
